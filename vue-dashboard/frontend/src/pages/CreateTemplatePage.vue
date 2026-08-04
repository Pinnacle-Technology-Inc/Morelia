<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { AlertTriangle, Check, ChevronRight, FolderPen, Plus, Radar, Trash2 } from "@lucide/vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import DeviceSettingsDialog from "../components/DeviceSettingsDialog.vue";
import FolderPickerDialog from "../components/FolderPickerDialog.vue";
import PageHeader from "../components/PageHeader.vue";
import StatusBadge from "../components/StatusBadge.vue";
import { loadDevicePool } from "../devices-api";
import { createSessionTemplate } from "../templates-api";
import { browseDirectories } from "../filesystem-api";
import { defaultSinkStem, uniqueSinkIdentifier } from "../template-import-utils";

const emit = defineEmits(["cancel", "created", "open-existing-template"]);

// Wizard state is snapshotted here so an accidental reload (or navigating away
// and back) mid-wizard doesn't discard in-progress work. Device configuration
// now happens in an inline dialog, so this no longer covers a Devices-page detour.
const SNAPSHOT_KEY = "create-template-draft";

// Sink types operators can attach to a stream. `file` sinks need a writable
// location on disk; service/plot sinks don't (mirrors the backend registry
// categories in app/services/registry.py).
const SINK_TYPES = [
  { value: "csv", label: "CSV", requiresLocation: true, extension: "csv" },
  { value: "edf", label: "EDF", requiresLocation: true, extension: "edf" },
  { value: "pvfs", label: "PVFS", requiresLocation: true, extension: "pvfs" },
  { value: "influx", label: "InfluxDB", requiresLocation: false },
  { value: "quest", label: "Quest", requiresLocation: false },
  { value: "plot", label: "Live plot", requiresLocation: false },
];

const step = ref(0);
const recoveryPolicy = ref("Recommend");
const templateName = ref("");
const devices = ref([]);
// Device discovery is a live serial scan, not a cached read, so the Streams step
// gets an explicit rescan for hardware plugged in after the page loaded.
const scanState = ref("idle");
const scanError = ref("");
const scannedAt = ref(null);
// False until a pool read has actually succeeded. Without it, a failed initial
// load leaves `devices` empty and every restored selection looks "missing",
// which blames the operator's hardware for what is really an offline backend.
const poolLoaded = ref(false);
const createState = ref("idle");
const createError = ref("");
// The `existing_template` summary from a 409 duplicate_template response, so
// Review can link straight to it instead of asking the operator to rename and
// retry (the backend never trusts a renamed resubmission over the original).
const duplicateTemplate = ref(null);

// Streams the operator has added as concrete examples of the devices this
// template requires, as device_config_ids, plus a parallel map of each
// stream's ordered sinks: { sink_type, sink_location }. Each stream's own
// `source_template` (the device template it was configured from) becomes the
// flow's device_template_path at submit time — see buildFlow().
const selectedConfigIds = ref([]);
const streamSinks = ref({});

// Sessions usually write every stream into one run folder, so the last folder
// picked seeds the next sink instead of restarting at the output root. Empty
// until the operator actually picks one — see the note in onMounted.
const lastUsedFolder = ref("");
// The host's configured output root, for describing where an unplaced sink
// goes. Display only; never written into a sink.
const defaultOutputFolder = ref("");
// Which sink the folder picker is open for: { configId, index } or null.
const folderPickerTarget = ref(null);

// The unconfigured pool row whose inline "Create device config" dialog is open,
// or null. Configuring a device happens in place here rather than by detouring
// to the Devices page, so an operator never loses the wizard mid-selection.
const configureTarget = ref(null);

// Streams and sinks are one step: picking a device and giving it an output is a
// single decision, and the two panes sit side by side so the sink editor reacts
// to the row you just ticked without a wizard hop.
const steps = ["Details", "Streams & Sinks", "Recovery", "Review"];
const progress = computed(() => `${Math.round(((step.value + 1) / steps.length) * 100)}%`);

// A device can only become a stream once it has a config; "free" is the pool's
// term for configured-and-unclaimed. Everything else in this list is present
// hardware the operator must go set up first.
function isSelectable(device) {
  return device.status === "free" && device.id != null;
}

// Devices the Streams step offers: physically present ("available") and not
// already claimed by another session. Unconfigured present hardware is included
// so operators can see (and go set up) devices that still need configuration.
// Selectable devices sort to the top so the actionable rows are the ones in
// view; sort() is stable, so the pool's own ordering survives within each group.
const streamDevices = computed(() =>
  devices.value
    .filter((device) => device.availability === "available" && device.status !== "claimed")
    .sort((a, b) => Number(isSelectable(b)) - Number(isSelectable(a))),
);

// The notice under the device table is a problem report, not a permanent
// caption. Standing orange on a finished, ready-to-create selection reads as
// "something is wrong", so it renders only when there is a blocker to name:
// hardware sitting in the list that has to be configured before it can be
// ticked. When there is none, the pane is quiet — which is itself the signal
// that the step is done.
const streamNotices = computed(() => {
  const notices = [];
  if (streamDevices.value.some((device) => !isSelectable(device))) {
    notices.push(
      "Only free configured devices can be added. Configure present-but-unconfigured devices right here — the dialog opens in place and the device joins your streams once saved.",
    );
  }
  return notices;
});

// Kept in sync with the header below so the empty-state row spans the full table.
const deviceColumnCount = 6;

// --- Stream selection ------------------------------------------------------

function isSelected(device) {
  return device.id != null && selectedConfigIds.value.includes(device.id);
}

function addStream(configId) {
  if (configId == null || selectedConfigIds.value.includes(configId)) return;
  selectedConfigIds.value = [...selectedConfigIds.value, configId];
  if (!streamSinks.value[configId]) streamSinks.value = { ...streamSinks.value, [configId]: [] };
}

function toggleStream(device) {
  if (!isSelectable(device)) {
    // Present but unconfigured. There is no chosen template to auto-configure
    // from here — this wizard is defining a template, not consuming one — so
    // this always opens the manual settings dialog.
    if (device.status === "unconfigured") configureDevice(device);
    return;
  }
  const id = device.id;
  if (selectedConfigIds.value.includes(id)) {
    selectedConfigIds.value = selectedConfigIds.value.filter((value) => value !== id);
    const next = { ...streamSinks.value };
    delete next[id];
    streamSinks.value = next;
  } else {
    addStream(id);
  }
}

// The joined device rows for the streams the operator has added, in add order.
const selectedStreams = computed(() =>
  selectedConfigIds.value
    .map((id) => devices.value.find((device) => device.id === id))
    .filter(Boolean),
);

// --- Sinks (block-until-complete gating) -----------------------------------

function streamSinkList(configId) {
  return streamSinks.value[configId] ?? [];
}

function sinkRequiresLocation(sinkType) {
  return SINK_TYPES.find((type) => type.value === sinkType)?.requiresLocation ?? false;
}

function sinkExtension(sinkType) {
  return SINK_TYPES.find((type) => type.value === sinkType)?.extension ?? "";
}

// A file sink's on-disk path is composed, not typed: the operator picks a folder
// (an absolute host path, from FolderPickerDialog) and types a name, and the
// extension follows the sink type so switching CSV -> EDF can't leave a
// mislabelled file behind. Returns "" while either half is missing, which is
// what streamIsValid() gates on.
function sinkLocationFor(sink, fallbackStem = "") {
  if (!sinkRequiresLocation(sink.sink_type)) return "";
  const folder = (sink.sink_folder ?? "").trim();
  // No folder means no explicit location at all — the backend places the file.
  // This is the gate that keeps an untouched sink on the deduplicating path.
  if (!folder) return "";
  // A chosen folder with no typed name still gets a location: they said where,
  // so we supply the what — the same stem the Name field was showing them.
  const name = (sink.sink_name ?? "").trim().replace(/[\\/]/g, "-") || fallbackStem;
  if (!name) return "";
  const extension = sinkExtension(sink.sink_type);
  const stem = name.toLowerCase().endsWith(`.${extension}`) ? name.slice(0, -(extension.length + 1)) : name;
  // Read the separator off the folder itself rather than tracking the host's
  // os.sep in component state: it survives a snapshot round-trip, and a
  // Windows path is unambiguous ("C:\data" can only join with a backslash).
  const separator = folder.includes("\\") ? "\\" : "/";
  const base = folder.endsWith(separator) ? folder.slice(0, -1) : folder;
  return `${base}${separator}${stem}.${extension}`;
}

// The filename a sink starts with, borrowed from what the backend would name it
// itself (manifests._allocate_sink_location): <device_id>-<sink_name>. Written
// in as a real value rather than a placeholder, so the Name column always says
// exactly what the file on disk will be called — the folder column shows where
// it goes, and the two together are the whole path with nothing implied.
function defaultSinkName(stream, sinkType, existing) {
  if (!stream) return "";
  return defaultSinkStem(stream, uniqueSinkIdentifier(sinkType, existing));
}

function addSink(configId) {
  const list = streamSinkList(configId);
  const stream = devices.value.find((device) => device.id === configId);
  const sink = {
    sink_type: "plot",
    sink_name: defaultSinkName(stream, "plot", list),
    sink_folder: lastUsedFolder.value || defaultOutputFolder.value,
  };
  streamSinks.value = { ...streamSinks.value, [configId]: [...list, sink] };
}

// Switching sink type has to re-derive a name that was only ever a default,
// otherwise a CSV renamed to EDF keeps "…-csv" in its filename. An operator's
// own name is left alone — it stops looking like a default the moment they
// change it.
function onSinkTypeChange(configId, index) {
  const list = [...streamSinkList(configId)];
  const stream = devices.value.find((device) => device.id === configId);
  const others = list.filter((_, position) => position !== index);
  const wasDefault = SINK_TYPES.some(
    (type) => list[index].sink_name === defaultSinkName(stream, type.value, others),
  );
  if (!wasDefault) return;
  list[index] = { ...list[index], sink_name: defaultSinkName(stream, list[index].sink_type, others) };
  streamSinks.value = { ...streamSinks.value, [configId]: list };
}

function removeSink(configId, index) {
  const list = [...streamSinkList(configId)];
  list.splice(index, 1);
  streamSinks.value = { ...streamSinks.value, [configId]: list };
}

// A stream needs a sink, and every file sink needs a resolvable destination.
// Both halves arrive pre-filled, so this only fails once an operator clears a
// name or folder — it marks an emptied field, not unfinished setup.
function streamIsValid(configId) {
  const list = streamSinkList(configId);
  if (!list.length) return false;
  return list.every((sink) => !sinkRequiresLocation(sink.sink_type) || Boolean(sinkLocationFor(sink)));
}

// A folder column is never wide enough for an absolute path, and plain ellipsis
// truncates the wrong end — "C:\Users\ahoang\Mo…" identifies nothing. The
// trailing segments are what actually name a destination, so keep those: two
// where they fit ("…\instance\output" distinguishes runs that share a leaf
// name), falling back to one on a deep path so the tile never shows a name cut
// mid-word. The tile's tooltip carries the whole path either way.
const FOLDER_TAIL_BUDGET = 24;

function shortFolder(path) {
  if (!path) return "";
  const separator = path.includes("\\") ? "\\" : "/";
  const segments = path.split(separator).filter(Boolean);
  if (segments.length <= 1) return path;
  const tail = segments.slice(-2).join(separator);
  if (segments.length === 2) return path;
  return `…${separator}${tail.length <= FOLDER_TAIL_BUDGET ? tail : segments[segments.length - 1]}`;
}

function openFolderPicker(configId, index) {
  folderPickerTarget.value = { configId, index };
}

function chooseFolder(path) {
  const target = folderPickerTarget.value;
  if (!target) return;
  const list = [...streamSinkList(target.configId)];
  list[target.index] = { ...list[target.index], sink_folder: path };
  streamSinks.value = { ...streamSinks.value, [target.configId]: list };
  lastUsedFolder.value = path;
  folderPickerTarget.value = null;
}

const folderPickerFolder = computed(() => {
  const target = folderPickerTarget.value;
  if (!target) return "";
  return streamSinkList(target.configId)[target.index]?.sink_folder ?? "";
});

// Streams the operator picked whose device is no longer in the pool — unplugged
// between selection and rescan, or claimed by another session meanwhile. They
// stay selected on purpose (dropping them would silently discard their sink
// config), but they are NOT in `selectedStreams`, so without this they'd be
// invisible on screen while still riding along in templatePayload().
const missingSelectedIds = computed(() =>
  poolLoaded.value
    ? selectedConfigIds.value.filter((id) => !devices.value.some((device) => device.id === id))
    : [],
);

function dropMissingStreams() {
  const missing = new Set(missingSelectedIds.value);
  selectedConfigIds.value = selectedConfigIds.value.filter((id) => !missing.has(id));
  const next = { ...streamSinks.value };
  for (const id of missing) delete next[id];
  streamSinks.value = next;
}

// Every added stream carries at least one valid sink — the gate the operator
// must clear before the template can be created.
const streamsComplete = computed(
  () => selectedConfigIds.value.length > 0 && selectedConfigIds.value.every(streamIsValid),
);

// --- Sequential step gating ------------------------------------------------
//
// Steps advance one at a time and each one has to stand on its own before the
// next is reachable, so a later step never renders against half-made decisions.
// Backwards movement stays free (the Back button); only forward is gated.

const detailsComplete = computed(() => Boolean(templateName.value.trim()));

const streamsStepComplete = computed(
  () => streamsComplete.value && missingSelectedIds.value.length === 0,
);

const canAdvance = computed(() => {
  if (step.value === 0) return detailsComplete.value;
  if (step.value === 1) return streamsStepComplete.value;
  return true;
});

// Why Next is disabled, in the operator's terms. Ordered by what they should
// deal with first rather than by how the checks happen to be written.
const advanceBlockedReason = computed(() => {
  if (canAdvance.value) return "";
  if (step.value === 0) return "Name this template to continue.";
  if (missingSelectedIds.value.length) return "Reconnect or remove the missing streams to continue.";
  if (!selectedConfigIds.value.length) return "Add at least one stream to continue.";
  return "Finish each stream's sinks to continue.";
});

const createDisabled = computed(
  () =>
    createState.value === "creating" ||
    !templateName.value.trim() ||
    !streamsComplete.value ||
    // Creating from a stream whose device left the pool would submit a flow
    // the operator can no longer see or fix if it's rejected.
    missingSelectedIds.value.length > 0,
);

// --- Snapshot persistence for the configure round-trip ---------------------

function persistSnapshot() {
  const snapshot = {
    step: step.value,
    recoveryPolicy: recoveryPolicy.value,
    templateName: templateName.value,
    selectedConfigIds: selectedConfigIds.value,
    streamSinks: streamSinks.value,
    lastUsedFolder: lastUsedFolder.value,
  };
  try {
    sessionStorage.setItem(SNAPSHOT_KEY, JSON.stringify(snapshot));
  } catch {
    /* storage unavailable (private mode / quota) — degrade to no persistence */
  }
}

function clearSnapshot() {
  try {
    sessionStorage.removeItem(SNAPSHOT_KEY);
  } catch {
    /* no-op */
  }
}

function restoreSnapshot() {
  let snapshot = null;
  try {
    snapshot = JSON.parse(sessionStorage.getItem(SNAPSHOT_KEY) ?? "null");
  } catch {
    snapshot = null;
  }
  if (!snapshot || typeof snapshot !== "object") return;
  // Clamp: a snapshot written before Streams and Sinks merged can carry a step
  // index past the end of the (now shorter) wizard, which would render nothing.
  step.value = Math.min(Math.max(snapshot.step ?? 0, 0), steps.length - 1);
  recoveryPolicy.value = snapshot.recoveryPolicy ?? "Recommend";
  templateName.value = snapshot.templateName ?? "";
  selectedConfigIds.value = Array.isArray(snapshot.selectedConfigIds) ? snapshot.selectedConfigIds : [];
  const sinks = snapshot.streamSinks && typeof snapshot.streamSinks === "object" ? snapshot.streamSinks : {};
  streamSinks.value = Object.fromEntries(
    Object.entries(sinks).map(([configId, list]) => [
      configId,
      (Array.isArray(list) ? list : []).map(migrateSink),
    ]),
  );
  lastUsedFolder.value = snapshot.lastUsedFolder ?? "";
}

// A snapshot written before the folder picker existed stores a single typed
// `sink_location`. Split it back into folder + name so an operator mid-wizard
// when this shipped doesn't silently lose their destinations.
function migrateSink(sink) {
  if (!sink || typeof sink !== "object") return sink;
  if (sink.sink_folder !== undefined || sink.sink_name !== undefined) return sink;
  const location = (sink.sink_location ?? "").replace(/\\/g, "/");
  const cut = location.lastIndexOf("/");
  return {
    sink_type: sink.sink_type,
    sink_folder: cut === -1 ? "" : location.slice(0, cut),
    sink_name: location.slice(cut + 1),
  };
}

// A restored snapshot can carry sinks whose name was left as an empty
// placeholder. Fill them from the same rule a fresh sink uses — the device
// rows have to be loaded first, so this runs after the pool arrives rather
// than inside restoreSnapshot().
function backfillSinkNames() {
  const next = { ...streamSinks.value };
  let changed = false;
  for (const [configId, list] of Object.entries(next)) {
    if (!list.some((sink) => !(sink.sink_name ?? "").trim())) continue;
    const stream = devices.value.find((device) => String(device.id) === String(configId));
    if (!stream) continue;
    const filled = [];
    for (const sink of list) {
      filled.push(
        (sink.sink_name ?? "").trim()
          ? sink
          : { ...sink, sink_name: defaultSinkName(stream, sink.sink_type, filled) },
      );
    }
    next[configId] = filled;
    changed = true;
  }
  if (changed) streamSinks.value = next;
}

// Persist on every meaningful change so a mid-wizard detour never loses work.
watch(
  [step, recoveryPolicy, templateName, selectedConfigIds, streamSinks],
  persistSnapshot,
  { deep: true },
);

// Re-run device discovery for hardware attached after this page loaded. The
// previous list is kept on screen while the scan runs (and on failure): a live
// scan takes a couple of seconds, and blanking the table mid-wizard would make
// already-selected streams flicker out of `selectedStreams`.
async function rescanDevices() {
  scanState.value = "scanning";
  scanError.value = "";
  try {
    const pool = await loadDevicePool();
    devices.value = pool.devices;
    scannedAt.value = pool.scannedAt;
    poolLoaded.value = true;
    scanState.value = "ready";
  } catch (reason) {
    scanState.value = "error";
    scanError.value = reason?.problem?.detail ?? reason?.message ?? "Device scan is unavailable.";
  }
}

// Opens the same settings dialog the Devices page uses, in create mode. No
// detour, no snapshot hand-off, no "resume wizard" banner to come back
// through — the device joins the wizard's streams once the dialog saves.
function configureDevice(device) {
  configureTarget.value = device;
}

async function onDeviceConfigured() {
  // Remember which physical device was being set up before we rescan — the dialog
  // reports "saved" but not the new config's id, and hardware_id is the stable
  // identity that survives the pool refresh.
  const hardwareId = configureTarget.value?.hardwareId ?? null;
  configureTarget.value = null;
  await rescanDevices();
  // "Configure and move on": the device is now configured and free, so add it as
  // a stream automatically. The operator's next click is its sink, not a re-tick.
  if (!hardwareId) return;
  const configured = devices.value.find((device) => device.hardwareId === hardwareId);
  if (configured && isSelectable(configured)) addStream(configured.id);
}

onMounted(async () => {
  restoreSnapshot();
  const [pool, defaultFolder] = await Promise.allSettled([loadDevicePool(), browseDirectories()]);
  if (pool.status === "fulfilled") {
    devices.value = pool.value.devices;
    scannedAt.value = pool.value.scannedAt;
    poolLoaded.value = true;
  }
  // Deliberately NOT seeded into `lastUsedFolder`: a pre-filled folder would be
  // indistinguishable from one the operator chose, and the two mean different
  // things to the backend (an explicit location fails on collision, an omitted
  // one deduplicates). Kept only to show where output lands by default — the
  // picker itself falls back to this same root when opened with a blank path.
  if (defaultFolder.status === "fulfilled") {
    defaultOutputFolder.value = defaultFolder.value.path ?? "";
  }
  backfillSinkNames();
});

// --- Submit ------------------------------------------------------------

function buildSink(sink, existing, stream) {
  const payload = { sink_type: sink.sink_type };
  // The Name column is the filename, and it doubles as the flow-local sink
  // identifier the backend needs (it defaults that to the sink type, which two
  // CSVs on one stream would collide on). Falling back to the generated name
  // keeps a cleared field from submitting an unnamed sink.
  const name = (sink.sink_name ?? "").trim();
  payload.sink_name = name || defaultSinkName(stream, sink.sink_type, existing);
  const location = sinkLocationFor(sink, payload.sink_name);
  if (location) payload.sink_location = location;
  if (sink.sink_parameters) payload.sink_parameters = sink.sink_parameters;
  return payload;
}

// Each selected stream is a concrete example of the hardware this template
// requires. Its own `configSource` — the device template that device's config
// was created from (devices-api.js maps this from the pool's `source_template`
// field) — becomes the flow's required device_template_path; nothing here
// carries the stream's device_config_id into the template.
function buildFlow(configId) {
  const stream = devices.value.find((device) => device.id === configId);
  const list = streamSinkList(configId);
  const flow = {
    device_template_path: stream?.configSource ?? null,
    // Each sink sees only the sinks before it, so identifiers are assigned in
    // list order and stay stable as later ones are added or removed.
    sinks: list.map((sink, index) => buildSink(sink, list.slice(0, index), stream)),
  };
  if (stream?.nickname) flow.nickname = stream.nickname;
  return flow;
}

function templatePayload() {
  return {
    name: templateName.value.trim(),
    policy: recoveryPolicy.value.toLowerCase(),
    device_flows: selectedConfigIds.value.map(buildFlow),
  };
}

function describeCreateError(error, fallback) {
  return error?.problem?.detail ?? error?.message ?? fallback;
}

async function createTemplate() {
  if (createDisabled.value) return;
  createState.value = "creating";
  createError.value = "";
  duplicateTemplate.value = null;
  try {
    const template = await createSessionTemplate(templatePayload());
    createState.value = "created";
    clearSnapshot();
    emit("created", template.template_id);
  } catch (error) {
    createState.value = "error";
    const problem = error?.problem;
    // A duplicate configuration is not this operator's mistake to fix by
    // renaming and resubmitting — the backend already has an ACTIVE template
    // with this exact content, so Review links straight to it.
    if (problem?.code === "duplicate_template" && problem?.existing_template) {
      duplicateTemplate.value = problem.existing_template;
      createError.value = describeCreateError(
        error,
        "A template with this exact configuration is already registered.",
      );
    } else {
      createError.value = describeCreateError(error, "Unable to create template.");
    }
  }
}

function onBack() {
  if (step.value === 0) {
    clearSnapshot();
    emit("cancel");
  } else {
    step.value -= 1;
  }
}
</script>

<template>
  <div class="page page--workspace">
    <PageHeader
      eyebrow="Guided configuration"
      title="Create Template"
      description="Define device-template requirements, streams, sinks, and recovery for a reusable session template."
    />
    <BaseCard class="wizard">
      <ol class="wizard-steps">
        <!-- Progress readout, not navigation: the wizard is sequential, so the
             chips report where you are rather than offering a jump. Disabled
             buttons keep the existing styling hooks and announce correctly. -->
        <li
          v-for="(label, index) in steps"
          :key="label"
          :class="{ active: index === step, complete: index < step }"
          :aria-current="index === step ? 'step' : undefined"
        >
          <button type="button" disabled>
            <span><Check v-if="index < step" :size="13" /><template v-else>{{ index + 1 }}</template></span>
            {{ label }}
          </button>
          <ChevronRight v-if="index < steps.length - 1" :size="15" />
        </li>
      </ol>
      <div class="wizard-progress"><i :style="{ width: progress }" /></div>

      <section class="wizard-content">
        <div v-if="step === 0" class="wizard-selection">
          <div class="form-grid">
            <label class="field field--wide">
              <span>Template Name</span>
              <input v-model="templateName" placeholder="e.g. bench-2-pod" />
            </label>
            <label class="field field--wide"><span>Description</span><input placeholder="Optional description" /></label>
          </div>
        </div>

        <!-- Streams (pane 1) and sinks (pane 2) read as one form. The panes are
             flex items with a wide basis, so they sit side by side while the
             card is roomy and wrap — sinks dropping below streams — when it
             isn't. Intrinsic wrapping, no media query: the wizard card, not the
             viewport, is what actually constrains them. -->
        <div v-else-if="step === 1" class="wizard-split streams-sinks">
          <section class="wizard-split__pane wizard-split__pane--first wizard-selection">
            <div class="streams-head">
              <h3>1 · Choose streams</h3>
              <BaseButton variant="secondary" :disabled="scanState === 'scanning'" @click="rescanDevices">
                <Radar :size="16" /> {{ scanState === "scanning" ? "Scanning…" : "Scan Devices" }}
              </BaseButton>
            </div>
            <p>Plugged something in just now? Scan Devices re-runs discovery.</p>
            <div v-if="scanState === 'error'" class="form-notice" role="alert"><AlertTriangle :size="18" /> {{ scanError }} Showing the previous scan.</div>
            <div v-if="missingSelectedIds.length" class="form-notice" role="alert">
              <AlertTriangle :size="18" />
              <span>
                {{ missingSelectedIds.length }} selected
                stream{{ missingSelectedIds.length === 1 ? " is" : "s are" }} no longer in the device pool —
                unplugged, or claimed by another session. Create is blocked until
                {{ missingSelectedIds.length === 1 ? "it is" : "they are" }} reconnected or removed.
              </span>
              <button type="button" class="table-action" @click="dropMissingStreams">Remove them</button>
            </div>
            <div class="table-wrap">
              <table class="data-table">
                <!-- Availability and Status are dropped: the list is already
                     filtered to available, unclaimed hardware, so both read the
                     same on every row, and "configured or not" is carried by the
                     checkbox-vs-warning cell. Config Source belongs to the
                     Devices page, not to picking a stream. -->
                <thead><tr><th class="select-col" /><th>Device</th><th>Type</th><th>Hardware ID</th><th>Port</th><th /></tr></thead>
                <tbody>
                  <tr v-if="!streamDevices.length"><td :colspan="deviceColumnCount">No available devices to stream from.</td></tr>
                  <tr
                    v-for="device in streamDevices"
                    :key="device.hardwareId"
                    :class="{
                      'row-selected': isSelected(device),
                      'row-selectable': isSelectable(device),
                      'row-unconfigured': !isSelectable(device),
                    }"
                    @click="toggleStream(device)"
                  >
                    <td class="select-cell">
                      <!-- @click.stop: the row handler already toggles, so let the
                           checkbox own its own click rather than firing twice. -->
                      <input
                        v-if="isSelectable(device)"
                        type="checkbox"
                        class="row-checkbox"
                        :checked="isSelected(device)"
                        :aria-label="`Stream from ${device.name}`"
                        @click.stop="toggleStream(device)"
                      />
                      <span
                        v-else
                        class="row-warning"
                        title="Configure this device before using it as a stream."
                        aria-label="Configure this device before using it as a stream."
                      ><AlertTriangle :size="16" /></span>
                    </td>
                    <td>
                      <strong>{{ device.name }}</strong>
                      <span v-if="!isSelectable(device)" class="row-warning-copy">Configure before use</span>
                    </td>
                    <td>{{ device.type }}</td>
                    <td><code>{{ device.hardwareId }}</code></td>
                    <td><code>{{ device.port }}</code></td>
                    <td>
                      <button
                        v-if="device.status !== 'free'"
                        type="button"
                        class="table-action"
                        @click.stop="configureDevice(device)"
                      >
                        Configure
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <!-- A running tally, not a verdict: it is muted once anything is
                 picked and amber only while the list is still empty. -->
            <p class="stream-count" :class="{ 'stream-count--empty': !selectedConfigIds.length }">{{ selectedConfigIds.length }} stream{{ selectedConfigIds.length === 1 ? "" : "s" }} selected.</p>
            <div v-if="streamNotices.length" class="form-notice" role="alert">
              <AlertTriangle :size="18" />
              <span>
                <span v-for="notice in streamNotices" :key="notice" class="stream-notice-line">{{ notice }}</span>
              </span>
            </div>
          </section>

          <section class="wizard-split__pane wizard-split__pane--second wizard-selection">
            <h3>2 · Configure sinks and outputs</h3>
            <p>Each stream needs at least one sink. File sinks (CSV, EDF, PVFS) are written to this session's output folder under the name shown — pick a folder only if they belong somewhere specific.</p>
            <div v-if="!selectedStreams.length" class="form-notice"><AlertTriangle :size="18" /> Tick a device to configure its outputs here.</div>
            <div v-for="stream in selectedStreams" :key="stream.id" class="stream-sink-group">
              <div class="stream-sink-head">
                <strong>{{ stream.name }}</strong>
                <span class="stream-sink-meta">{{ stream.type }} · {{ stream.port }}</span>
                <StatusBadge compact :value="streamIsValid(stream.id) ? 'Ready' : 'Needs sink'" />
                <BaseButton variant="secondary" @click="addSink(stream.id)"><Plus :size="16" /> Add Sink</BaseButton>
              </div>
              <div class="table-wrap">
                <table class="data-table">
                  <thead><tr><th>Sink Type</th><th>Name</th><th>Folder</th><th /></tr></thead>
                  <tbody>
                    <tr v-if="!streamSinkList(stream.id).length"><td colspan="4">No sinks yet — add one above.</td></tr>
                    <tr v-for="(sink, index) in streamSinkList(stream.id)" :key="index">
                      <td><select v-model="sink.sink_type" class="sink-control sink-control--select" @change="onSinkTypeChange(stream.id, index)"><option v-for="type in SINK_TYPES" :key="type.value" :value="type.value">{{ type.label }}</option></select></td>
                      <td>
                        <!-- The filename, extension excluded — it follows the
                             sink type, so switching CSV to EDF can't leave a
                             mislabelled file behind. -->
                        <div class="sink-name">
                          <input v-model="sink.sink_name" class="sink-control" aria-label="Sink filename" :title="sink.sink_name" />
                          <span v-if="sinkRequiresLocation(sink.sink_type)" class="sink-extension">.{{ sinkExtension(sink.sink_type) }}</span>
                        </div>
                      </td>
                      <td>
                        <!-- One tile, one job: the folder. The filename lives in
                             its own column, so nothing here restates it and the
                             row reads left to right as name + place. -->
                        <button
                          v-if="sinkRequiresLocation(sink.sink_type)"
                          type="button"
                          class="sink-control sink-folder-tile"
                          :aria-label="`Change folder for ${sink.sink_name || sink.sink_type}`"
                          :title="sinkLocationFor(sink) || 'Choose a folder for this sink'"
                          @click="openFolderPicker(stream.id, index)"
                        >
                          <span class="sink-folder-path">{{ shortFolder(sink.sink_folder) || "Choose a folder…" }}</span>
                          <FolderPen :size="16" class="sink-folder-icon" />
                        </button>
                        <span v-else>—</span>
                      </td>
                      <td><button type="button" class="table-action table-action--icon" title="Remove sink" aria-label="Remove sink" @click="removeSink(stream.id, index)"><Trash2 :size="14" /></button></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <FolderPickerDialog
              v-if="folderPickerTarget"
              :model-value="folderPickerFolder"
              @select="chooseFolder"
              @close="folderPickerTarget = null"
            />
          </section>

          <!-- Inline device configuration: same dialog the Devices page uses,
               opened in create mode for an unconfigured pool row. On save we
               rescan and auto-add the now-free device as a stream. -->
          <DeviceSettingsDialog
            v-if="configureTarget"
            :device="configureTarget"
            @close="configureTarget = null"
            @saved="onDeviceConfigured"
          />
        </div>

        <div v-else-if="step === 2" class="wizard-selection">
          <h3>Recovery</h3>
          <p>What the watchdog may do on its own when a stream faults mid-run.</p>
          <div class="form-grid">
            <label class="field field--wide"><span>Recovery Policy</span><select v-model="recoveryPolicy"><option>Recommend</option><option>Automate</option></select></label>
            <div class="form-notice field--wide"><AlertTriangle :size="18" /> Changed policies default to Recommend. Automation requires an explicit choice.</div>
            <BaseCard class="field--wide detail-panel">
              <dl class="detail-list">
                <div><dt>Recommend</dt><dd>Report software-fixable faults and wait for operator approval.</dd></div>
                <div><dt>Automate</dt><dd>Run software-fixable recovery when preconditions allow it.</dd></div>
              </dl>
            </BaseCard>
          </div>
        </div>

        <div v-else class="review-state">
          <div v-if="!streamsComplete" class="form-notice"><AlertTriangle :size="18" /> Complete stream and sink selection before creating.</div>
          <dl class="detail-list">
            <div><dt>Template name</dt><dd>{{ templateName.trim() || "—" }}</dd></div>
            <div><dt>Streams</dt><dd>{{ selectedConfigIds.length }} stream{{ selectedConfigIds.length === 1 ? "" : "s" }} selected</dd></div>
            <div><dt>Sinks &amp; outputs</dt><dd>{{ streamsComplete ? "Configured" : "Selection required" }}</dd></div>
            <div><dt>Recovery policy</dt><dd>{{ recoveryPolicy }}</dd></div>
          </dl>
          <div v-if="createError" class="form-notice" role="alert">
            <AlertTriangle :size="18" />
            <span>{{ createError }}</span>
            <button
              v-if="duplicateTemplate"
              type="button"
              class="table-action"
              @click="emit('open-existing-template', duplicateTemplate.template_id)"
            >
              Open {{ duplicateTemplate.name }}
            </button>
          </div>
        </div>
      </section>

      <footer class="wizard-footer">
        <BaseButton variant="secondary" @click="onBack">{{ step === 0 ? "Cancel" : "Back" }}</BaseButton>
        <div>
          <span v-if="createError" role="alert" class="validation-copy">{{ createError }}</span>
          <span v-else-if="advanceBlockedReason" class="validation-copy">{{ advanceBlockedReason }}</span>
          <BaseButton v-if="step < steps.length - 1" :disabled="!canAdvance" @click="step++">Next: {{ steps[step + 1] }}</BaseButton>
          <BaseButton v-else :disabled="createDisabled" @click="createTemplate">{{ createState === "creating" ? "Creating…" : "Create Template" }}</BaseButton>
        </div>
      </footer>
    </BaseCard>
  </div>
</template>

<style scoped>
/* Two-pane wizard step: a pair of sections that read as one form side by side
   and stack when the card is too narrow to seat both. Used by Streams & Sinks.
   Each instance tunes the two custom properties. */
.wizard-split {
  /* One knob for the split, expressed as the first pane's share of the row.
     Both panes' widths derive from it, so rebalancing is a single edit. */
  --split-share: 50%;
  --pane-min: 26rem;

  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: var(--space-6);
  /* Lets the divider below key off this row's own width instead of the
     viewport's, so it appears and disappears exactly when the panes wrap. */
  container-type: inline-size;
}
.wizard-split__pane {
  flex-grow: 1;
  flex-shrink: 1;
  /* An explicit min-width does two jobs: it overrides the automatic
     content-based minimum (which the device table would otherwise inflate past
     the pane's share), and it sets the wrap threshold — two panes stop fitting
     once the row can't seat both at this width. min() keeps a lone wrapped pane
     from overflowing a card narrower than --pane-min. */
  min-width: min(var(--pane-min), 100%);
  /* .wizard-selection caps itself at 900px; here the shares own the widths, and
     leaving the cap on would strand space on wide screens. */
  max-width: none;
}
/* Each pane subtracts half the gap, so the two bases plus the gap total exactly
   100%. That leaves no free space for flex-grow to hand out, which is what
   holds the ratio at --split-share for every card width — grow distributes only
   the surplus past the basis, so encoding the split there instead drifts. */
.wizard-split__pane--first {
  flex-basis: calc(var(--split-share) - var(--space-6) / 2);
}
.wizard-split__pane--second {
  flex-basis: calc(100% - var(--split-share) - var(--space-6) / 2);
}
/* A rule between the panes while they're side by side. Once they wrap, the
   second pane starts a new line and the border would read as a stray vertical
   mark — so it's drawn only above the wrap threshold, 2 × --pane-min + gap.
   A container query can't read a custom property, so each instance restates
   its own threshold as a literal; keep these in step with --pane-min above.
   The query targets the panes rather than the row because a container can't
   style itself, only its descendants. */
/* The sink editor carries four columns, one of them an absolute path; the
   device list is five narrow ones. An even split starves the side that needs the
   room, so the streams pane gives some back. */
.streams-sinks {
  --split-share: 42%;
}
@container (min-width: 54rem) {
  .streams-sinks > .wizard-split__pane--second {
    padding-left: var(--space-6);
    border-left: 1px solid var(--border-card);
  }
}
/* form-grid caps at 820px for full-width steps; inside a pane the share governs. */
.wizard-split .form-grid {
  max-width: none;
}
/* The step chips report progress rather than offering navigation, so they carry
   the styling of the existing buttons without the affordance. `opacity: 1`
   overrides the UA's disabled dimming — these are labels, not dead controls. */
.wizard-steps button:disabled {
  opacity: 1;
  cursor: default;
}
/* .validation-copy is red by force (it carries !important in styles.css), so a
   line that switches between "why you're blocked" and ordinary guidance needs
   its own escape back to muted. */
.hint-copy {
  color: var(--muted) !important;
}
/* The stream tally used .validation-copy, which paints it red unconditionally —
   so a healthy two-stream selection looked like a failed one. Red is reserved
   for "you did something wrong"; an empty list is merely unfinished, so it gets
   amber, and any non-zero count drops to muted like the caption it is. */
.stream-count {
  color: var(--muted);
}
.stream-count--empty {
  color: var(--warning);
}
/* .form-notice is a flex row, so multiple messages would otherwise run together
   on one line beside the icon. */
.stream-notice-line {
  display: block;
}
.stream-notice-line + .stream-notice-line {
  margin-top: var(--space-2);
}
/* Browser default placeholder colour varies (Chrome uses a solid grey, Firefox
   applies opacity), so pin it to the muted token. */
.field input::placeholder,
.field textarea::placeholder {
  color: var(--text-muted);
  opacity: 1;
}
/* styles.css floors every table at 780px, which is wider than a pane and would
   force a horizontal scrollbar inside each one. With the columns trimmed there's
   nothing left that needs the floor, so drop it and let the table fit its pane.
   .table-wrap keeps overflow-x as the escape hatch for very narrow cards. */
.streams-sinks .data-table {
  min-width: 0;
}
/* Global cell padding (16px/24px) is tuned for full-width tables; halve the
   horizontal share to buy back roughly 60px per row at these widths. */
.streams-sinks .data-table th,
.streams-sinks .data-table td {
  padding-right: var(--space-3);
  padding-left: var(--space-3);
}
.streams-sinks .data-table td {
  padding-top: var(--space-3);
  padding-bottom: var(--space-3);
}
/* Auto table layout only compresses a column as far as its content's min-content
   width. Hardware IDs and ports are unbroken strings, so without this they'd act
   as struts holding the table wider than its pane. */
.streams-sinks .data-table code {
  overflow-wrap: anywhere;
}
/* Same problem, different cause: an <input>'s intrinsic minimum comes from its
   `size` attribute (~20 chars), which the sink table's three controls would sum
   into an overflow. min-width: 0 lets width: 100% actually govern. */
.streams-sinks .sink-control {
  min-width: 0;
}
/* The sink table is the one place where a cell holds something unboundedly long
   (an absolute folder path). Under `table-layout: auto` the column sizes to that
   string — 426px of path forced the table to 780px inside a 473px pane, and
   `min-width: 0` can't help because the demand comes from content, not a floor.
   Fixed layout makes the declared widths authoritative, which is also what
   finally lets the ellipsis in .sink-folder-path engage. */
.stream-sink-group .data-table {
  width: 100%;
  table-layout: fixed;
}
/* Proportional rather than fixed: these panes range from ~26rem when wrapped to
   whatever a wide card gives them, and rem widths that fit one end starve the
   other. Folder takes the larger share — a path is longer than a filename and
   is the value an operator scans for. Name gives up the room it was using to
   seat the longest generated filename exactly; those now scroll inside the
   input, which carries the full value in a tooltip. */
.stream-sink-group .data-table th:nth-child(1),
.stream-sink-group .data-table td:nth-child(1) {
  width: 18%;
}
.stream-sink-group .data-table th:nth-child(2),
.stream-sink-group .data-table td:nth-child(2) {
  width: 33%;
}
.stream-sink-group .data-table th:nth-child(3),
.stream-sink-group .data-table td:nth-child(3) {
  width: 41%;
}
.stream-sink-group .data-table th:nth-child(4),
.stream-sink-group .data-table td:nth-child(4) {
  width: 8%;
}
/* Table cells are padded for wide layouts; inside these four narrow columns
   that padding is the difference between a filename fitting and not. */
.stream-sink-group .data-table td {
  padding-right: var(--space-2);
  padding-left: var(--space-2);
}
.table-action--icon {
  padding-right: var(--space-2);
  padding-left: var(--space-2);
}
/* Only free devices can be toggled; unconfigured rows keep the default cursor
   so the row doesn't advertise an affordance that toggleStream() rejects. */
.row-selectable {
  cursor: pointer;
}
.row-selectable:hover {
  background: var(--sage-50);
}
/* Inset bar rather than a border so the row's height doesn't shift on select. */
.row-selected {
  background: var(--sage-100);
  box-shadow: inset 3px 0 0 var(--accent);
}
.row-selected:hover {
  background: var(--sage-200);
}
/* Unconfigured hardware sits below the selectable rows: muted text, warning
   glyph where the checkbox would be. It is still clickable — a click opens the
   settings dialog and adds it as a stream — so it keeps the pointer that
   advertises that. */
.row-unconfigured {
  color: var(--text-muted);
  cursor: pointer;
}
.row-unconfigured:hover {
  background: var(--sage-50);
}
.row-unconfigured strong {
  font-weight: 500;
}
.row-warning {
  display: inline-flex;
  color: var(--warning);
}
.row-warning-copy {
  display: block;
  color: var(--warning);
  font-size: var(--fs-xs);
}
.select-col {
  width: 2.5rem;
}
.select-cell {
  text-align: center;
}
.row-checkbox {
  width: 16px;
  height: 16px;
  accent-color: var(--accent);
  cursor: pointer;
}
.stream-sink-group {
  margin: 1rem 0;
  padding: 1rem;
  border: 1px solid var(--border, #e2e8f0);
  border-radius: 0.5rem;
}
.stream-sink-head {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}
.stream-sink-head .button {
  margin-left: auto;
}
.stream-sink-meta {
  color: var(--text-muted, #64748b);
  font-size: 0.85rem;
}
/* The sink table's controls live in bare <td>s, so they miss the `.field`
   selector in styles.css that dresses every other form control. Same tokens,
   trimmed height for table density. */
.sink-control {
  width: 100%;
  min-height: 36px;
  padding: var(--space-2) var(--space-3);
  color: var(--text-body);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-md);
  background: var(--surface-sage);
  font-size: var(--fs-sm);
}
.streams-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}
.streams-head h3 {
  margin: 0;
}
/* Name + extension read as one field: the input carries the editable stem and
   the suffix sits inside the same box, greyed, so the row shows the whole
   filename without letting anyone type an extension that contradicts the type. */
.sink-name {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding-right: var(--space-3);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-md);
  background: var(--surface-sage);
}
/* Right-aligned so an overlong filename shows its TAIL. The generated default
   leads with the device type, which is identical for every sink on a stream —
   left alignment spends the visible width on the part that distinguishes
   nothing and hides the part that does. The caret still lands where clicked. */
.sink-name .sink-control {
  border: 0;
  background: none;
  text-align: left;
}
.sink-name:focus-within {
  border-color: var(--primary, var(--border-card));
}
.sink-extension {
  color: var(--muted);
  font-size: var(--fs-sm);
  white-space: nowrap;
}
/* The folder tile. Its whole surface is the control, so the trailing "Change"
   and the pen icon are there to say so — a bare path in a box reads as a
   disabled text field otherwise. */
.sink-folder-tile {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  text-align: left;
  cursor: pointer;
}
.sink-folder-tile:hover,
.sink-folder-tile:focus-visible {
  border-color: var(--primary, var(--border-card));
  background: var(--sage-50);
}
/* The path is the flexible part: it truncates, the icon and hint never do. */
.sink-folder-path {
  flex: 1 1 auto;
  overflow: hidden;
  min-width: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* The pen sits after the path, where a select's caret would be, so the tile
   reads as something you open. A text label here would cost more width than it
   earns at this column size — the icon, the hover state and the tooltip carry
   it instead. */
.sink-folder-icon {
  flex: 0 0 auto;
  color: var(--muted);
}
.sink-folder-tile:hover .sink-folder-icon {
  color: var(--primary, var(--ink));
}
.sink-control--select {
  /* Native select chrome ignores the tokens above, so draw our own caret. */
  appearance: none;
  padding-right: var(--space-6);
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%236b7a70' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m4 6 4 4 4-4'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right var(--space-3) center;
  background-size: 14px;
  cursor: pointer;
}
</style>
