<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { AlertTriangle, Check, ChevronRight, FolderPen, Plus, Radar, Trash2 } from "@lucide/vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import DeviceSettingsDialog from "../components/DeviceSettingsDialog.vue";
import DeviceTemplateDriftDialog from "../components/DeviceTemplateDriftDialog.vue";
import FolderPickerDialog from "../components/FolderPickerDialog.vue";
import PageHeader from "../components/PageHeader.vue";
import StatusBadge from "../components/StatusBadge.vue";
import {
  createDeviceConfigFromTemplate,
  editDeviceConfig,
  loadDeviceConfig,
  loadDevicePool,
} from "../devices-api";
import { loadDeviceTemplates, loadSessionTemplateCatalog } from "../templates-api";
import { loadAssignmentPlan } from "../template-planner-api";
import { loadExperiments } from "../experiments-api";
import { createSessionDraft, loadSessionNameSuggestion, startSession } from "../session-api";
import { browseDirectories } from "../filesystem-api";
import {
  compareParameters,
  defaultSinkStem,
  deviceTemplateForFlow,
  hasDrift,
  matchFlowIndex,
  templateSinksForFlow,
  uniqueSinkIdentifier,
} from "../template-import-utils";

const emit = defineEmits(["cancel", "saved", "started"]);

// Wizard state is snapshotted here so an accidental reload (or navigating away
// and back) mid-wizard doesn't discard in-progress work. Device configuration
// now happens in an inline dialog, so this no longer covers a Devices-page detour.
const SNAPSHOT_KEY = "create-session-draft";

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
const startFrom = ref("Blank session");
const recoveryPolicy = ref("Recommend");
const sessionTemplates = ref([]);
// The device-template library, needed to read the *parameters* a session
// template's flow expects. The assignment planner resolves each flow only as
// far as a device type, so the settings comparison has to be done here.
const deviceTemplates = ref([]);
const experiments = ref([]);
const experimentId = ref("");
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
const templateName = ref("");
const planner = ref(null);
const plannerState = ref("idle");
const plannerError = ref("");
const sessionName = ref("");
// The name the backend would mint if we submit without one. Shown as the Name
// field's placeholder and echoed on Review, but deliberately never written into
// sessionName: the moment it becomes the field's *value* it would be submitted
// as an explicit name, which skips the backend's auto-naming path and — if the
// guess went stale behind a concurrent create — collides and picks up a "-1"
// suffix. Left as a placeholder, an empty field still sends null and the
// backend assigns the authoritative name from the real row id.
const suggestedName = ref("");
const saveState = ref("idle");
const saveError = ref("");
const draftId = ref(null);
const startState = ref("idle");

// Streams the operator has added to this session, as device_config_ids, plus a
// parallel map of each stream's ordered sinks: { sink_type, sink_location }.
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

// --- Session-template authority -------------------------------------------
//
// When a session template is chosen, its flows are the authority on how each
// device should be configured. Three pieces of bookkeeping carry that:
//
//   flowClaims   which template flow each selected device stands in for, so two
//                devices of the same type don't both answer to flow 0.
//   driftQueue   devices whose saved settings disagree with their flow's device
//                template, awaiting an operator decision. Non-empty blocks Next.
//   driftChoices what was decided, kept for the Review step.
const flowClaims = ref({});
const driftQueue = ref([]);
const driftChoices = ref({});
const driftDialogOpen = ref(false);
const driftBusy = ref(false);
const driftError = ref("");
// A device whose config could not be read can't be compared. That's an
// assistive check, not a safety barrier — the backend still validates at start —
// so a failed read reports itself instead of wedging the wizard.
const driftCheckError = ref("");
const autoConfigureState = ref("idle");
const autoConfigureError = ref("");
// Set when a template's pinned output folder doesn't resolve on this host.
const templateFolderWarning = ref("");

// The catalog arrives asynchronously, but a restored snapshot can set
// templateName before it lands. Anything that reads template *content* waits on
// this so a mid-wizard reload plans against the same data a fresh visit would.
let markCatalogReady;
const catalogReady = new Promise((resolve) => {
  markCatalogReady = resolve;
});

const selectedSessionTemplate = computed(
  () => sessionTemplates.value.find((template) => template.reference === templateName.value) ?? null,
);

const templateFlows = computed(() => {
  const flows = selectedSessionTemplate.value?.content?.device_flows;
  return Array.isArray(flows) ? flows : [];
});

function templateForFlow(flow) {
  return deviceTemplateForFlow(flow, deviceTemplates.value);
}

// Which flow a device answers to. The planner already bound flows to specific
// configs, so an assigned device uses its own flow_index; anything the operator
// ticked by hand falls through to first-unclaimed-of-this-type.
function claimFlowIndex(device) {
  const flows = templateFlows.value;
  if (!flows.length) return null;
  const assignment = assignmentByConfigId.value.get(device.id);
  if (assignment) return assignment.flow_index;
  const claimed = [
    ...Object.values(flowClaims.value),
    ...[...assignmentByConfigId.value.values()].map((assigned) => assigned.flow_index),
  ];
  return matchFlowIndex(device, flows, deviceTemplates.value, claimed);
}

// Compare one selected device against its flow's device template, queueing a
// decision when they disagree. Silent when there is no template to answer to.
// A template flow describes outputs as well as settings, so a stream added
// under a template starts with the sinks that flow asks for. Only seeded into
// an empty sink list: once the operator has touched a stream's outputs, they
// own them.
// Sinks restored from a snapshot written when the Name field was a placeholder
// carry an empty name, which would now read as a cleared field and block the
// step. Fill them from the same rule a fresh sink uses — the device rows have
// to be loaded first, so this runs after the pool arrives rather than inside
// restoreSnapshot().
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

// Is a template's pinned destination actually a folder we can write to? A
// session template travels between machines and outlives the paths it names, and
// its sink_location may have meant a FILE — an earlier run of this very template
// can have left one sitting at that exact path. Adopting either blind hands the
// operator a destination the runtime is guaranteed to fail on, so ask the host.
// Answers are cached: several flows usually share one folder.
const folderChecks = new Map();

async function folderIsUsable(path) {
  if (!path) return false;
  if (folderChecks.has(path)) return folderChecks.get(path);
  const check = browseDirectories(path)
    .then((listing) => Boolean(listing?.exists && listing?.writable))
    // A failed probe is not proof the folder is bad; let it through rather than
    // silently discarding a destination the template author chose on purpose.
    .catch(() => true);
  folderChecks.set(path, check);
  return check;
}

async function seedSinksFromFlow(configId, flow) {
  if (streamSinkList(configId).length) return;
  const imported = templateSinksForFlow(flow);
  if (!imported.length) return;
  // A template that pins a destination sets the working folder for whatever the
  // operator adds next, the same way picking one by hand does — but only once
  // we know the path still resolves to somewhere writable.
  const pinned = imported.find((sink) => sink.sink_folder)?.sink_folder;
  if (pinned && !(await folderIsUsable(pinned))) {
    templateFolderWarning.value =
      `This template's output folder (${pinned}) is missing or not writable on this machine, ` +
      `so its sinks fall back to the session output folder. Pick another folder to override that.`;
    for (const sink of imported) sink.sink_folder = "";
  } else if (pinned) {
    lastUsedFolder.value = pinned;
  }
  // Fill the blanks the template left. A flow that names its sink keeps that
  // name; one that doesn't falls back to the same device-derived filename a
  // hand-added sink would get, so every row reads the same way.
  const stream = devices.value.find((device) => device.id === configId);
  const filled = [];
  for (const sink of imported) {
    filled.push({
      ...sink,
      sink_name: sink.sink_name || defaultSinkName(stream, sink.sink_type, filled),
      sink_folder: sink.sink_folder || lastUsedFolder.value || defaultOutputFolder.value,
    });
  }
  streamSinks.value = { ...streamSinks.value, [configId]: filled };
}

async function checkDeviceAgainstTemplate(device) {
  const flowIndex = claimFlowIndex(device);
  if (flowIndex == null) return;
  flowClaims.value = { ...flowClaims.value, [device.id]: flowIndex };
  await seedSinksFromFlow(device.id, templateFlows.value[flowIndex]);
  const template = templateForFlow(templateFlows.value[flowIndex]);
  if (!template) return;
  if (driftQueue.value.some((entry) => entry.configId === device.id)) return;

  let config;
  try {
    config = await loadDeviceConfig(device.id);
    driftCheckError.value = "";
  } catch (error) {
    driftCheckError.value =
      error?.problem?.detail ?? error?.message ?? `Could not read ${device.name}'s settings to compare them.`;
    return;
  }
  // Fast path: the config was minted from this exact template revision, so its
  // parameters are that template's by construction.
  if (config.source_template_hash && config.source_template_hash === template.content_hash) return;

  const rows = compareParameters(template.content?.parameters ?? {}, config.parameters ?? {});
  if (!hasDrift(rows)) return;
  driftQueue.value = [...driftQueue.value, { configId: device.id, device, template, rows }];
  driftDialogOpen.value = true;
}

const currentDrift = computed(() => driftQueue.value[0] ?? null);

// What the operator decided, for the Review step. "Kept their own" is the one
// worth surfacing: those devices will run with settings the template disowns.
const driftSummary = computed(() => {
  const choices = Object.values(driftChoices.value);
  return {
    template: choices.filter((choice) => choice === "template").length,
    device: choices.filter((choice) => choice === "device").length,
  };
});

async function resolveDrift(choice) {
  const current = currentDrift.value;
  if (!current) return;
  if (choice === "device") {
    // Keep the device as it is: the session simply runs with settings that
    // differ from the template. Nothing is written.
    driftChoices.value = { ...driftChoices.value, [current.configId]: "device" };
    dequeueDrift();
    return;
  }
  driftBusy.value = true;
  driftError.value = "";
  try {
    // Adopt the template wholesale — edit() replaces parameters rather than
    // merging, which is what makes the strict rule (drop what the template does
    // not mention) fall out without any per-key deletion here.
    await editDeviceConfig(current.configId, {
      parameters: current.template.content?.parameters ?? {},
      source_template: current.template.file_path,
    });
    driftChoices.value = { ...driftChoices.value, [current.configId]: "template" };
    dequeueDrift();
  } catch (error) {
    driftError.value =
      error?.problem?.detail ?? error?.message ?? "Could not apply the template's settings.";
  } finally {
    driftBusy.value = false;
  }
}

function dequeueDrift() {
  driftQueue.value = driftQueue.value.slice(1);
  driftError.value = "";
  driftDialogOpen.value = driftQueue.value.length > 0;
}

// Forgetting a device's template bookkeeping when it leaves the selection —
// otherwise a deselected device keeps blocking Next from inside the queue.
function forgetDevice(configId) {
  driftQueue.value = driftQueue.value.filter((entry) => entry.configId !== configId);
  driftDialogOpen.value = driftDialogOpen.value && driftQueue.value.length > 0;
  const claims = { ...flowClaims.value };
  delete claims[configId];
  flowClaims.value = claims;
  const choices = { ...driftChoices.value };
  delete choices[configId];
  driftChoices.value = choices;
}

function clearStreamSelection() {
  selectedConfigIds.value = [];
  streamSinks.value = {};
  flowClaims.value = {};
  driftQueue.value = [];
  driftChoices.value = {};
  driftDialogOpen.value = false;
  driftError.value = "";
  driftCheckError.value = "";
  templateFolderWarning.value = "";
}

// Streams and sinks are one step: picking a device and giving it an output is a
// single decision, and the two panes sit side by side so the sink editor reacts
// to the row you just ticked without a wizard hop.
const steps = ["Details", "Streams & Sinks", "Schedule & Recovery", "Review"];
const progress = computed(() => `${Math.round(((step.value + 1) / steps.length) * 100)}%`);

// Device types the template picked in Details requires. `null` means no template
// (blank session), so the Streams step imposes no type restriction.
const requiredDeviceTypes = computed(() => {
  const plan = planner.value;
  if (!plan) return null;
  const types = new Set();
  for (const assignment of plan.assignments ?? []) if (assignment.device_type) types.add(assignment.device_type);
  for (const requirement of plan.unresolved_requirements ?? []) if (requirement.device_type) types.add(requirement.device_type);
  return types;
});

// Pool row `id` == backend device_config_id, so we can join a device to the
// planner's assignment to surface its exact/generic match.
const assignmentByConfigId = computed(() => {
  const map = new Map();
  for (const assignment of planner.value?.assignments ?? []) {
    if (assignment.device_config_id != null) map.set(assignment.device_config_id, assignment);
  }
  return map;
});

// A device can only become a stream once it has a config; "free" is the pool's
// term for configured-and-unclaimed. Everything else in this list is present
// hardware the operator must go set up first.
function isSelectable(device) {
  return device.status === "free" && device.id != null;
}

// Devices the Streams step offers: physically present ("available") and not
// already claimed by another session. Unconfigured present hardware is included
// so operators can see (and go set up) devices that still need configuration.
// When a template is selected, the list is restricted to its required types.
// Selectable devices sort to the top so the actionable rows are the ones in
// view; sort() is stable, so the pool's own ordering survives within each group.
const streamDevices = computed(() =>
  devices.value
    .filter((device) => {
      if (device.availability !== "available") return false;
      if (device.status === "claimed") return false;
      const types = requiredDeviceTypes.value;
      if (types && types.size > 0 && !types.has(device.type)) return false;
      return true;
    })
    .sort((a, b) => Number(isSelectable(b)) - Number(isSelectable(a))),
);

// The notice under the device table is a problem report, not a permanent
// caption. Standing orange on a finished, ready-to-start selection reads as
// "something is wrong", so it renders only when there is a blocker to name: a
// template requirement no present device can satisfy, or hardware sitting in the
// list that has to be configured before it can be ticked. When neither holds,
// the pane is quiet — which is itself the signal that the step is done.
const streamNotices = computed(() => {
  const notices = (planner.value?.unresolved_requirements ?? []).map(
    (requirement) => `${requirement.message} Start remains blocked until this requirement is resolved.`,
  );
  if (streamDevices.value.some((device) => !isSelectable(device))) {
    notices.push(
      "Only free configured devices can be added. Configure present-but-unconfigured devices right here — the dialog opens in place and the device joins your streams once saved.",
    );
  }
  return notices;
});

function deviceMatch(device) {
  return assignmentByConfigId.value.get(device.id)?.match ?? null;
}

// Match only says anything once a template has produced assignments, so the
// column earns its width on the template path and is dropped on the blank one.
const showMatchColumn = computed(() => Boolean(planner.value?.assignments?.length));

// Kept in sync with the header below so the empty-state row spans the full table.
const deviceColumnCount = computed(() => (showMatchColumn.value ? 7 : 6));

// --- Stream selection ------------------------------------------------------

function isSelected(device) {
  return device.id != null && selectedConfigIds.value.includes(device.id);
}

function addStream(configId) {
  if (configId == null || selectedConfigIds.value.includes(configId)) return;
  selectedConfigIds.value = [...selectedConfigIds.value, configId];
  if (!streamSinks.value[configId]) streamSinks.value = { ...streamSinks.value, [configId]: [] };
}

async function toggleStream(device) {
  if (!isSelectable(device)) {
    // Present but unconfigured. With a session template active this configures
    // the device from the template's device template and adds it in one click —
    // there are no existing settings to weigh, so nothing to confirm.
    if (device.status === "unconfigured") await configureDevice(device);
    return;
  }
  const id = device.id;
  if (selectedConfigIds.value.includes(id)) {
    selectedConfigIds.value = selectedConfigIds.value.filter((value) => value !== id);
    const next = { ...streamSinks.value };
    delete next[id];
    streamSinks.value = next;
    forgetDevice(id);
  } else {
    addStream(id);
    await checkDeviceAgainstTemplate(device);
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
// invisible on screen while still riding along in draftPayload().
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
  for (const id of missing) forgetDevice(id);
}

// Every added stream carries at least one valid sink — the gate the operator
// must clear before a draft can be saved or the session started.
const streamsComplete = computed(
  () => selectedConfigIds.value.length > 0 && selectedConfigIds.value.every(streamIsValid),
);

// A blank draft (no streams yet) is a legal save; a draft with a half-configured
// stream is not (the backend rejects a flow with no sink), so block that.
const canPersist = computed(() => selectedConfigIds.value.length === 0 || streamsComplete.value);

const templateReady = computed(
  () => startFrom.value !== "Session template" || (planner.value?.complete && plannerState.value === "ready"),
);

// --- Sequential step gating ------------------------------------------------
//
// Steps advance one at a time and each one has to stand on its own before the
// next is reachable, so a later step never renders against half-made decisions.
// Backwards movement stays free (the Back button); only forward is gated.

// Details is done once a chosen template has actually been planned. A plan with
// unresolved requirements still passes: the operator resolves those on the
// Streams step by plugging hardware in and rescanning, and `startDisabled`
// keeps Start blocked until they do.
const detailsComplete = computed(
  () =>
    startFrom.value !== "Session template" ||
    (Boolean(templateName.value) && plannerState.value === "ready"),
);

const streamsStepComplete = computed(
  () => streamsComplete.value && missingSelectedIds.value.length === 0 && driftQueue.value.length === 0,
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
  if (step.value === 0) {
    if (!templateName.value) return "Choose a session template to continue.";
    if (plannerState.value === "loading") return "Planning assignments…";
    return "This template's assignment plan is unavailable.";
  }
  if (driftQueue.value.length) {
    return `Confirm settings for ${driftQueue.value.length} device${driftQueue.value.length === 1 ? "" : "s"} to continue.`;
  }
  if (missingSelectedIds.value.length) return "Reconnect or remove the missing streams to continue.";
  if (!selectedConfigIds.value.length) return "Add at least one stream to continue.";
  return "Finish each stream's sinks to continue.";
});

const startDisabled = computed(
  () =>
    startState.value === "starting" ||
    !streamsComplete.value ||
    !templateReady.value ||
    // Starting a flow whose device left the pool fails at spawn time anyway;
    // blocking here turns a confusing runtime error into a fixable warning.
    missingSelectedIds.value.length > 0,
);

// --- Snapshot persistence for the configure round-trip ---------------------

function persistSnapshot() {
  const snapshot = {
    step: step.value,
    startFrom: startFrom.value,
    recoveryPolicy: recoveryPolicy.value,
    sessionName: sessionName.value,
    experimentId: experimentId.value,
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
  startFrom.value = snapshot.startFrom ?? "Blank session";
  recoveryPolicy.value = snapshot.recoveryPolicy ?? "Recommend";
  sessionName.value = snapshot.sessionName ?? "";
  experimentId.value = snapshot.experimentId ?? "";
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

// Persist on every meaningful change so a mid-wizard detour never loses work.
watch(
  [step, startFrom, recoveryPolicy, sessionName, experimentId, templateName, selectedConfigIds, streamSinks],
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

async function configureDevice(device) {
  autoConfigureError.value = "";
  const flowIndex = claimFlowIndex(device);
  const template = flowIndex == null ? null : templateForFlow(templateFlows.value[flowIndex]);
  // Nothing to adopt — a blank session, a flow with no device-template link, or
  // hardware with no stable identity to key a config on. Configure in place:
  // the same dialog the Devices page uses, in create mode. No detour, no
  // snapshot hand-off, no "resume session creation" banner to come back through.
  if (!template || !device.hardwareId) {
    configureTarget.value = device;
    return;
  }

  // The template path needs no confirmation: an unconfigured device has no
  // settings to lose, so it simply becomes what the session template asks for.
  autoConfigureState.value = "configuring";
  try {
    await createDeviceConfigFromTemplate({
      template_name: template.name,
      hardware_id: device.hardwareId,
      port: device.port,
      nickname: device.nickname ?? null,
    });
    await rescanDevices();
    const configured = devices.value.find((row) => row.hardwareId === device.hardwareId);
    if (configured && isSelectable(configured)) {
      addStream(configured.id);
      // Created *from* the template, so its parameters are that template's by
      // construction — record the claim and skip the comparison entirely. The
      // flow's outputs still have to be imported.
      flowClaims.value = { ...flowClaims.value, [configured.id]: flowIndex };
      driftChoices.value = { ...driftChoices.value, [configured.id]: "template" };
      await seedSinksFromFlow(configured.id, templateFlows.value[flowIndex]);
    }
    autoConfigureState.value = "idle";
  } catch (error) {
    autoConfigureState.value = "error";
    autoConfigureError.value =
      error?.problem?.detail ??
      error?.message ??
      `Could not configure ${device.name} from ${template.name}.`;
  }
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
  if (configured && isSelectable(configured)) {
    addStream(configured.id);
    // Hand-authored settings can still contradict the template this session is
    // built from, so the same comparison applies as for any other selection.
    await checkDeviceAgainstTemplate(configured);
  }
}

onMounted(async () => {
  restoreSnapshot();
  const [pool, templates, deviceTemplateList, exps, defaultFolder, nameSuggestion] =
    await Promise.allSettled([
      loadDevicePool(),
      loadSessionTemplateCatalog(),
      loadDeviceTemplates(),
      loadExperiments(),
      browseDirectories(),
      loadSessionNameSuggestion(),
    ]);
  if (pool.status === "fulfilled") {
    devices.value = pool.value.devices;
    scannedAt.value = pool.value.scannedAt;
    poolLoaded.value = true;
  }
  // Same folder-authoritative catalog as Templates. Skip unreadable drafts
  // (content null) — they can't plan. Select value is catalog `reference`
  // so stored vs local copies of the same name stay distinct.
  if (templates.status === "fulfilled") {
    sessionTemplates.value = templates.value.filter((template) => template?.content != null);
  }
  if (deviceTemplateList.status === "fulfilled") {
    deviceTemplates.value = Array.isArray(deviceTemplateList.value) ? deviceTemplateList.value : [];
  }
  // Releases anything waiting to read template content — see `catalogReady`.
  // Fired unconditionally: a failed catalog load must not leave the planner
  // waiting forever, it should plan against what it has and report the gap.
  markCatalogReady();
  if (exps.status === "fulfilled") experiments.value = Array.isArray(exps.value) ? exps.value : [];
  // Cosmetic: on failure the placeholder just falls back to generic copy, and
  // an untouched Name field still gets its real name assigned on save.
  if (nameSuggestion.status === "fulfilled") suggestedName.value = nameSuggestion.value;
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

watch(templateName, async (name) => {
  planner.value = null;
  plannerError.value = "";
  if (!name) return;
  plannerState.value = "loading";
  // The plan is read against the catalog entry's flows below, so both have to
  // describe the same template — wait for the catalog before planning.
  await catalogReady;
  try {
    planner.value = await loadAssignmentPlan(name);
    plannerState.value = "ready";
    // A template's resolved assignments become pre-selected streams the operator
    // can then attach sinks to (or remove) — unifying the template and manual paths.
    for (const assignment of planner.value.assignments ?? []) {
      addStream(assignment.device_config_id);
    }
    // Compare every selected device, not just the ones the planner assigned.
    // Assignments match a flow to a device on *type* alone, so a pre-selected
    // device can still contradict the flow's device template — and a snapshot
    // restored mid-wizard arrives with manual picks already selected, which
    // would otherwise reach Review without ever having been checked.
    for (const configId of selectedConfigIds.value) {
      const device = devices.value.find((row) => row.id === configId);
      if (device) await checkDeviceAgainstTemplate(device);
    }
  } catch (error) {
    plannerState.value = "unavailable";
    plannerError.value = error instanceof Error ? error.message : "Assignment planning is unavailable.";
  }
});

// --- Guarded Details edits -------------------------------------------------

// Changing the template re-decides every stream below it, so an operator with
// work in progress is asked first. The native <select> has already moved to the
// new option by the time this runs, hence the explicit DOM restore on cancel.
function confirmDiscardStreams() {
  const count = selectedConfigIds.value.length;
  if (count === 0) return true;
  return window.confirm(
    `This will clear your ${count} selected stream${count === 1 ? "" : "s"} and their sinks. Continue?`,
  );
}

function requestTemplateChange(event) {
  const next = event.target.value;
  if (next === templateName.value) return;
  if (!confirmDiscardStreams()) {
    event.target.value = templateName.value;
    return;
  }
  clearStreamSelection();
  templateName.value = next;
}

function requestStartFromChange(event) {
  const next = event.target.value;
  if (next === startFrom.value) return;
  if (!confirmDiscardStreams()) {
    event.target.value = startFrom.value;
    return;
  }
  clearStreamSelection();
  startFrom.value = next;
  // Leaving the template path drops the template itself, which clears the
  // planner through the watch above.
  if (next !== "Session template") templateName.value = "";
}

function buildSink(sink, existing, stream) {
  const payload = { sink_type: sink.sink_type };
  // The Name column is the filename, and it doubles as the flow-local sink
  // identifier the backend needs (it defaults that to the sink type, which two
  // CSVs on one stream would collide on). Falling back to the generated name
  // keeps a cleared field from submitting an unnamed sink.
  const name = (sink.sink_name ?? "").trim();
  payload.sink_name = name || defaultSinkName(stream, sink.sink_type, existing);
  const location = sinkLocationFor(sink, payload.sink_name);
  // A whole absolute host path. resolve_sink_location() passes absolute values
  // through byte-for-byte, so the runtime opens exactly the file the wizard
  // showed — no re-rooting, no separator rewriting.
  if (location) payload.sink_location = location;
  if (sink.sink_parameters) payload.sink_parameters = sink.sink_parameters;
  return payload;
}

function draftPayload() {
  return {
    name: sessionName.value.trim() || null,
    policy: recoveryPolicy.value.toLowerCase(),
    experiment_id: experimentId.value || null,
    device_flows: selectedConfigIds.value.map((configId) => {
      const stream = devices.value.find((device) => device.id === configId);
      const list = streamSinkList(configId);
      // Each sink sees only the sinks before it, so identifiers are assigned in
      // list order and stay stable as later ones are added or removed.
      return {
        device_config_id: configId,
        sinks: list.map((sink, index) => buildSink(sink, list.slice(0, index), stream)),
      };
    }),
  };
}

async function saveDraft({ navigate = true } = {}) {
  saveState.value = "saving";
  saveError.value = "";
  try {
    const session = await createSessionDraft(draftPayload());
    draftId.value = session.id;
    saveState.value = "saved";
    clearSnapshot();
    emit("saved", session.id);
    if (navigate && session?.id != null) window.location.hash = `#session/${session.id}`;
  } catch (error) {
    saveState.value = "error";
    saveError.value = describeSaveError(error, "Unable to save draft.");
  }
}

// A 409 sink_location_exists carries `suggested_location` as an RFC 9457
// extension field, computed by next_available_path — the backend's own
// "<stem>-<session>-<n>" postfix. Surfacing it turns "that file exists" into
// something the operator can act on without inventing a name.
//
// It is reported rather than applied because the wizard sends no flow
// nicknames, so the error's label can't be tied back to one specific sink row
// when several streams share a filename.
function describeSaveError(error, fallback) {
  const problem = error?.problem;
  const detail = problem?.detail ?? error?.message ?? fallback;
  if (problem?.code === "sink_location_exists" && problem?.suggested_location) {
    return `${detail} A free name is available: ${problem.suggested_location}. Rename the sink, or clear its folder to let the session place the file.`;
  }
  return detail;
}

async function startDraft() {
  if (startDisabled.value) return;
  if (!draftId.value) {
    await saveDraft({ navigate: false });
    if (!draftId.value) return;
  }
  startState.value = "starting";
  saveError.value = "";
  try {
    const session = await startSession(draftId.value);
    startState.value = "started";
    clearSnapshot();
    // Announce the start before navigating. Without this the wizard changed a
    // session's lifecycle and the catalog never heard about it — the row stayed
    // Draft on Overview and Sessions until the operator reloaded the app.
    emit("started", session?.id ?? draftId.value);
    if (session?.id != null) window.location.hash = `#session/${session.id}`;
  } catch (error) {
    startState.value = "error";
    saveError.value = describeSaveError(error, "Unable to start draft.");
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

function deviceLabel(value) {
  return { available: "Available", not_found: "Not found", unopenable: "Unopenable", free: "Free", claimed: "Claimed", exact: "Exact", generic: "Generic" }[value] ?? value;
}

function templateOptionLabel(template) {
  if (template.source === "local") return `${template.name} (draft)`;
  return template.name;
}
</script>

<template>
  <div class="page page--workspace">
    <PageHeader
      eyebrow="Guided configuration"
      title="Create Session"
      description="Choose streams, outputs, scheduling, and guarded recovery behavior."
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
        <div v-if="step === 0" class="wizard-split wizard-split--forms">
          <section class="wizard-split__pane wizard-split__pane--first wizard-selection">
            <div class="form-grid">
              <label class="field field--wide">
                <span>Session Name</span>
                <!-- Shows the backend's generated name (e.g. "Session 10") as a
                     placeholder rather than a value: an empty field submits null,
                     which is what makes the backend mint the authoritative name.
                     Typing replaces it as usual. -->
                <input v-model="sessionName" :placeholder="suggestedName" />
              </label>
              <label class="field field--wide"><span>Description</span><input placeholder="Optional description" /></label>
              <label class="field"><span>Experiment</span><select v-model="experimentId"><option value="">None</option><option v-for="experiment in experiments" :key="experiment.id" :value="experiment.id">{{ experiment.name }}</option></select></label>
              <!-- Both selects are guarded rather than v-modelled: changing
                   either one invalidates every stream chosen below it, so the
                   handler confirms before letting the change land. -->
              <label class="field"><span>Start From</span><select :value="startFrom" @change="requestStartFromChange"><option>Blank session</option><option>Session template</option></select></label>
              <label v-if="startFrom === 'Session template'" class="field field--wide"><span>Session Template</span><select :value="templateName" @change="requestTemplateChange"><option value="">Choose a session template</option><option v-for="template in sessionTemplates" :key="`${template.source}:${template.reference}`" :value="template.reference">{{ templateOptionLabel(template) }}</option></select></label>
              <p v-if="startFrom === 'Session template'" class="field--wide validation-copy" :class="{ 'hint-copy': detailsComplete }">
                <template v-if="plannerState === 'loading'">Planning device assignments…</template>
                <template v-else-if="detailsComplete">This template's device settings take priority over each device's own configuration.</template>
                <template v-else>{{ advanceBlockedReason }}</template>
              </p>
            </div>
          </section>

          <section class="wizard-split__pane wizard-split__pane--second wizard-selection">
            <label class="field notes-field"><span>Notes</span><textarea placeholder="Optional session notes" /></label>
          </section>
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
            <div v-if="autoConfigureError" class="form-notice" role="alert"><AlertTriangle :size="18" /> {{ autoConfigureError }}</div>
            <div v-if="driftCheckError" class="form-notice" role="alert">
              <AlertTriangle :size="18" />
              <span>{{ driftCheckError }} Its settings were not compared against the template.</span>
            </div>
            <!-- Closing the dialog defers a decision rather than making one, so
                 the queue stays visible with a way back into it. -->
            <div v-if="driftQueue.length && !driftDialogOpen" class="form-notice" role="alert">
              <AlertTriangle :size="18" />
              <span>
                {{ driftQueue.length }}
                device{{ driftQueue.length === 1 ? "" : "s" }}
                {{ driftQueue.length === 1 ? "has" : "have" }} settings that differ from this
                session's template. Next is blocked until you choose.
              </span>
              <button type="button" class="table-action" @click="driftDialogOpen = true">Review</button>
            </div>
            <div v-if="missingSelectedIds.length" class="form-notice" role="alert">
              <AlertTriangle :size="18" />
              <span>
                {{ missingSelectedIds.length }} selected
                stream{{ missingSelectedIds.length === 1 ? " is" : "s are" }} no longer in the device pool —
                unplugged, or claimed by another session. Start is blocked until
                {{ missingSelectedIds.length === 1 ? "it is" : "they are" }} reconnected or removed.
              </span>
              <button type="button" class="table-action" @click="dropMissingStreams">Remove them</button>
            </div>
            <div v-if="plannerState === 'loading'">Planning assignments…</div>
            <div v-else-if="plannerState === 'unavailable'" class="form-notice" role="alert">{{ plannerError }}</div>
            <div v-if="planner?.warnings?.length" class="form-notice"><AlertTriangle :size="18" /><span v-for="warning in planner.warnings" :key="warning.flow_index">{{ warning.message }} Alternatives: {{ warning.alternatives.map(item => item.hardware_id).join(", ") || "none" }}.</span></div>
            <div class="table-wrap">
              <table class="data-table">
                <!-- Availability and Status are dropped: the list is already
                     filtered to available, unclaimed hardware, so both read the
                     same on every row, and "configured or not" is carried by the
                     checkbox-vs-warning cell. Config Source belongs to the
                     Devices page, not to picking a stream. -->
                <thead><tr><th class="select-col" /><th>Device</th><th>Type</th><th v-if="showMatchColumn">Match</th><th>Hardware ID</th><th>Port</th><th /></tr></thead>
                <tbody>
                  <tr v-if="!streamDevices.length"><td :colspan="deviceColumnCount">{{ requiredDeviceTypes?.size ? "No available devices match this template's device types." : "No available devices to stream from." }}</td></tr>
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
                    <td v-if="showMatchColumn"><StatusBadge v-if="deviceMatch(device)" compact :value="deviceLabel(deviceMatch(device))" /><span v-else>—</span></td>
                    <td><code>{{ device.hardwareId }}</code></td>
                    <td><code>{{ device.port }}</code></td>
                    <td>
                      <button
                        v-if="device.status !== 'free'"
                        type="button"
                        class="table-action"
                        :disabled="autoConfigureState === 'configuring'"
                        @click.stop="configureDevice(device)"
                      >
                        {{ autoConfigureState === "configuring" ? "Configuring…" : "Configure" }}
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
            <p v-if="startFrom === 'Session template'">Sinks defined by the session template are added automatically when you add a stream.</p>
            <div v-if="templateFolderWarning" class="form-notice" role="alert"><AlertTriangle :size="18" /> <span>{{ templateFolderWarning }}</span></div>
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

          <!-- The session template and the device disagree about how this
               device should be set up. One decision per device, queued so a
               template that pre-selects several is worked through in order. -->
          <DeviceTemplateDriftDialog
            v-if="driftDialogOpen && currentDrift"
            :device="currentDrift.device"
            :template-name="currentDrift.template.name"
            :rows="currentDrift.rows"
            :busy="driftBusy"
            :error="driftError"
            @choose="resolveDrift"
            @close="driftDialogOpen = false"
          />
        </div>

        <!-- Schedule and recovery are both "how should this run unattended?"
             settings and fit in a screen together. Same two-pane mechanism as
             Streams & Sinks, tuned narrower since these are short form fields. -->
        <div v-else-if="step === 2" class="wizard-split wizard-split--forms">
          <section class="wizard-split__pane wizard-split__pane--first wizard-selection">
            <h3>1 · Schedule</h3>
            <p>When the session should start. Manual leaves it to an operator.</p>
            <div class="form-grid">
              <label class="field"><span>Start Mode</span><select><option>Manual</option><option>One-time</option><option>Daily</option></select></label>
              <label class="field"><span>Timezone</span><select><option>America/Chicago</option></select></label>
              <label class="field"><span>Start Date</span><input type="date" /></label>
              <label class="field"><span>Start Time</span><input type="time" /></label>
            </div>
          </section>

          <section class="wizard-split__pane wizard-split__pane--second wizard-selection">
            <h3>2 · Recovery</h3>
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
          </section>
        </div>

        <div v-else class="review-state">
          <div v-if="!streamsComplete" class="form-notice"><AlertTriangle :size="18" /> Complete stream and sink selection before starting.</div>
          <dl class="detail-list">
            <div><dt>Session details</dt><dd>{{ sessionName.trim() || suggestedName || "Auto-generated on save" }}</dd></div>
            <div><dt>Streams</dt><dd>{{ selectedConfigIds.length }} stream{{ selectedConfigIds.length === 1 ? "" : "s" }} selected</dd></div>
            <div><dt>Sinks &amp; outputs</dt><dd>{{ streamsComplete ? "Configured" : "Selection required" }}</dd></div>
            <div v-if="startFrom === 'Session template'">
              <dt>Template settings</dt>
              <dd>
                <template v-if="driftSummary.device">
                  {{ driftSummary.device }} device{{ driftSummary.device === 1 ? "" : "s" }} keeping
                  {{ driftSummary.device === 1 ? "its" : "their" }} own settings<template v-if="driftSummary.template">,
                  {{ driftSummary.template }} using the template's</template>.
                </template>
                <template v-else-if="driftSummary.template">
                  All {{ driftSummary.template }} device{{ driftSummary.template === 1 ? "" : "s" }} using the template's settings.
                </template>
                <template v-else>Every device already matches the template.</template>
              </dd>
            </div>
            <div><dt>Schedule</dt><dd>Manual</dd></div>
            <div><dt>Recovery policy</dt><dd>{{ recoveryPolicy }}</dd></div>
          </dl>
        </div>
      </section>

      <footer class="wizard-footer">
        <BaseButton variant="secondary" @click="onBack">{{ step === 0 ? "Cancel" : "Back" }}</BaseButton>
        <div>
          <span v-if="saveError" role="alert" class="validation-copy">{{ saveError }}</span>
          <span v-else-if="!canPersist" class="validation-copy">Finish each stream's sinks to save.</span>
          <span v-else-if="advanceBlockedReason" class="validation-copy">{{ advanceBlockedReason }}</span>
          <BaseButton variant="secondary" :disabled="saveState === 'saving' || !canPersist" @click="saveDraft">{{ saveState === 'saving' ? "Saving…" : "Save as Draft" }}</BaseButton>
          <BaseButton v-if="step < steps.length - 1" :disabled="!canAdvance" @click="step++">Next: {{ steps[step + 1] }}</BaseButton>
          <BaseButton v-else :disabled="startDisabled" @click="startDraft">{{ startState === "starting" ? "Starting…" : "Start Now" }}</BaseButton>
        </div>
      </footer>
    </BaseCard>
  </div>
</template>

<style scoped>
/* Two-pane wizard step: a pair of sections that read as one form side by side
   and stack when the card is too narrow to seat both. Used by Streams & Sinks
   and by Schedule & Recovery; instances tune the two custom properties. */
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
/* Schedule & Recovery holds short form fields rather than tables, so it packs
   into narrower panes and stays side by side further down. */
.wizard-split--forms {
  --pane-min: 21rem;
}
/* A rule between the panes while they're side by side. Once they wrap, the
   second pane starts a new line and the border would read as a stray vertical
   mark — so it's drawn only above the wrap threshold, 2 × --pane-min + gap.
   A container query can't read a custom property, so each instance restates
   its own threshold as a literal; keep these in step with --pane-min above.
   The query targets the panes rather than the row because a container can't
   style itself, only its descendants. */
/* The sink editor carries four columns, one of them an absolute path; the
   device list is six narrow ones. An even split starves the side that needs the
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
@container (min-width: 44rem) {
  .wizard-split--forms > .wizard-split__pane--second {
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
   applies opacity), so pin it to the muted token. This is what marks the
   suggested session name as a suggestion rather than a filled-in value. */
.field input::placeholder,
.field textarea::placeholder {
  color: var(--text-muted);
  opacity: 1;
}
/* Notes is the only control in its pane, so give it the height the neighbouring
   form would otherwise leave as dead space. */
.notes-field textarea {
  min-height: 14rem;
  resize: vertical;
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
   glyph where the checkbox would be. It is still clickable — a click configures
   it (from the session template when there is one) and adds it as a stream — so
   it keeps the pointer that advertises that. */
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
