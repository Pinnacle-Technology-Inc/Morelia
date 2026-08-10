<script setup>
// Starting a run from a registered template, as a modal over the template it
// starts from. The template owns the configuration — stream count, sink types,
// sink order, recovery — and this collects only what belongs to one run: which
// physical device fills each flow, where each file sink writes, and the run's
// own metadata.
//
// Device assignment is a live scan rather than a typed device_config_id: the id
// is an internal key an operator has no way to know, and the pool already
// carries everything needed to choose (name, hardware id, port, whether it is
// free). The planner's suggestion arrives pre-selected, so the common case is a
// glance rather than a decision.
import { computed, onMounted, onBeforeUnmount, ref, watch } from "vue";
import { AlertTriangle, FolderPen, RefreshCw, X } from "@lucide/vue";
import BaseButton from "./BaseButton.vue";
import DeviceScanTable from "./DeviceScanTable.vue";
import FolderPickerDialog from "./FolderPickerDialog.vue";
import StatusBadge from "./StatusBadge.vue";
import {
  buildTemplateRunPayload,
  composeSinkLocation,
  createTemplateRun,
  isFileSink,
  loadSessionNameSuggestion,
  templateRevisionChanged,
} from "../session-api";
import { createDeviceConfigFromTemplate, isDeviceSelectable, loadDevicePool } from "../devices-api";
import { browseDirectories } from "../filesystem-api";
import { outputFolder, validateOutputFolders } from "../sink-location-recovery";
import { compatiblePoolDevicesForFlow, deviceTypeForFlow, loadAssignmentPlan } from "../template-planner-api";
import { loadDeviceTemplates, loadSessionTemplate, templateStateHint } from "../templates-api";
import {
  defaultRunFileStem,
  normalizeTemplateRef,
  sessionNameFromSuggestion,
} from "../template-import-utils";

const props = defineProps({
  templateId: { type: String, required: true },
});
const emit = defineEmits(["cancel", "created", "template-stale"]);

const template = ref(null);
const loadedRevision = ref(null);
const assignmentPlan = ref(null);
const assignments = ref([]);
const loadState = ref("loading");
const submitState = ref("idle");
const loadError = ref("");
const submitError = ref("");
const folderValidationError = ref("");
const nameSuggestion = ref("");
const stale = ref(false);

const name = ref("");
const experimentId = ref("");
const notes = ref("");
const runMode = ref("start");
const scheduleAt = ref("");
const requestIdentity = ref({ fingerprint: "", key: "" });

// Device discovery is a live serial scan, so the assignment step gets an
// explicit rescan for hardware plugged in after the dialog opened.
const devices = ref([]);
const deviceTemplates = ref([]);
const scanState = ref("idle");
const scanError = ref("");
const defaultOutputFolder = ref("");

// Which sink the folder picker is open for: { flowIndex, sinkIndex } or null.
const folderPickerTarget = ref(null);
const configuringHardware = new Set();
// A rejected create carrying the backend's proposed alternative path, so a
// collision is one click to resolve rather than a path to retype.
const collision = ref(null);

const flows = computed(() => template.value?.content?.device_flows ?? []);
const submitting = computed(() => submitState.value === "creating");

// The template's sinks per flow, in the shape this form edits around them.
//
// Deliberately walks `flow.sinks` unfiltered: a position in this list IS the
// `sink_index` the payload sends, and the backend resolves that index against
// the frozen snapshot's own sink list (session_config._locations_by_index). Any
// view that dropped or reordered an entry would silently address the wrong sink.
//
// A template's stored sink_location is read as a FOLDER, not a file path — a
// template is a reusable recipe, so its destination means "put this run's output
// here"; taking it as an exact filename would make the second run from that
// template fail with SinkLocationExists. Same reading as templateSinksForFlow().
const templateSinks = computed(() =>
  flows.value.map((flow) =>
    (flow.sinks ?? []).map((sink) => {
      const sinkName = (sink.sink_name ?? "").trim();
      return {
        sink_type: sink.sink_type,
        // A name that merely equals the type is the backend's own default
        // written out, not a name anybody chose — keeping it would pin a file
        // called "csv.csv".
        sink_name: sinkName === sink.sink_type ? "" : sinkName,
        sink_folder: (sink.sink_location ?? "").trim(),
      };
    }),
  ),
);

function describeError(error, fallback) {
  return error?.problem?.detail ?? error?.message ?? fallback;
}

function deviceFor(configId) {
  return configId == null ? null : devices.value.find((device) => device.id === configId) ?? null;
}

function plannerAssignment(flowIndex) {
  return assignmentPlan.value?.assignments?.find((item) => item.flow_index === flowIndex) ?? null;
}

// --- Device candidates per flow --------------------------------------------

function matchesFlowTemplate(device, flowIndex) {
  const required = normalizeTemplateRef(flows.value[flowIndex]?.device_template_path);
  // A pool row may not report its source template at all (see gap register
  // D-01/D-02). Unknown is not "wrong": it must not rank a device below one we
  // positively know is a mismatch, and it must never hide it from the list.
  const source = normalizeTemplateRef(device.configSource);
  return Boolean(required) && Boolean(source) && required === source;
}

function deviceTemplateForFlow(flowIndex) {
  const required = normalizeTemplateRef(flows.value[flowIndex]?.device_template_path);
  return deviceTemplates.value.find(
    (template) => normalizeTemplateRef(template.file_path) === required,
  ) ?? null;
}

function requiredDeviceType(flowIndex) {
  return deviceTypeForFlow(assignmentPlan.value, flowIndex) ?? deviceTemplateForFlow(flowIndex)?.type ?? null;
}

// One device cannot fill two flows of one run, so a device taken by another
// flow leaves this flow's list entirely rather than sitting there un-tickable.
function candidateDevices(flowIndex) {
  // Rank, high to low: the device this flow's template asks for, any other free
  // device, then present-but-unconfigured hardware. sort() is stable, so the
  // pool's own ordering survives within each band.
  const rank = (device) => {
    if (!isPreferenceSelectable(device)) return 0;
    return matchesFlowTemplate(device, flowIndex) ? 2 : 1;
  };
  return compatiblePoolDevicesForFlow(devices.value, {
    flowIndex,
    assignments: assignments.value,
    deviceType: requiredDeviceType(flowIndex),
    scheduled: runMode.value === "schedule",
  }).sort((a, b) => rank(b) - rank(a));
}

function isPreferenceSelectable(device) {
  if (runMode.value !== "schedule") return isDeviceSelectable(device);
  return device?.id != null && device.status !== "unconfigured";
}

function annotateFor(flowIndex) {
  return (device) => {
    const planned = plannerAssignment(flowIndex);
    if (planned && planned.device_config_id === device.id) {
      return planned.match ? `Planner: ${planned.match} match` : "Planner suggestion";
    }
    if (matchesFlowTemplate(device, flowIndex)) return "Matches the required device template";
    return "";
  };
}

function assignDevice(flowIndex, device) {
  const assignment = assignments.value[flowIndex];
  if (!assignment) return;
  // Radio semantics: re-clicking the assigned device clears it, which is the
  // only way to undo an assignment without picking a different one.
  assignment.deviceConfigId = assignment.deviceConfigId === device.id ? null : device.id;
}

// --- Sink destinations ------------------------------------------------------

const sessionNamePreview = computed(() =>
  sessionNameFromSuggestion(nameSuggestion.value, name.value),
);

function defaultFileOrdinal(flowIndex, sinkIndex) {
  const targetType = templateSinks.value[flowIndex]?.[sinkIndex]?.sink_type;
  const targetConfigId = assignments.value[flowIndex]?.deviceConfigId;
  let ordinal = 0;
  for (let currentFlow = 0; currentFlow <= flowIndex; currentFlow += 1) {
    if (assignments.value[currentFlow]?.deviceConfigId !== targetConfigId) continue;
    const sinks = templateSinks.value[currentFlow] ?? [];
    const lastSink = currentFlow === flowIndex ? sinkIndex : sinks.length - 1;
    for (let currentSink = 0; currentSink <= lastSink; currentSink += 1) {
      if (isFileSink(sinks[currentSink]?.sink_type) && sinks[currentSink].sink_type === targetType) {
        ordinal += 1;
      }
    }
  }
  return Math.max(ordinal, 1);
}

// The filename this sink writes when the operator types nothing: the
// hyphenated template/session/run identity followed by device code and name.
function defaultSinkName(flowIndex, sinkIndex) {
  const device = deviceFor(assignments.value[flowIndex]?.deviceConfigId);
  if (!device) return "";
  const sinks = templateSinks.value[flowIndex] ?? [];
  const sink = sinks[sinkIndex];
  if (!sink) return "";
  return defaultRunFileStem(
    sessionNamePreview.value,
    device,
    defaultFileOrdinal(flowIndex, sinkIndex),
  );
}

function sinkName(flowIndex, sinkIndex) {
  const typed = (assignments.value[flowIndex]?.sinks?.[sinkIndex]?.name ?? "").trim();
  return typed || defaultSinkName(flowIndex, sinkIndex);
}

// The rows are driven by `templateSinks` (which the backend indexes against)
// while the edits live on `assignments`. A revision that drifts mid-form
// replaces the first before this dialog unmounts, so every read of the second
// goes through a guard rather than assuming the two are still the same length.
function sinkEdit(flowIndex, sinkIndex) {
  return assignments.value[flowIndex]?.sinks?.[sinkIndex] ?? null;
}

function setSinkName(flowIndex, sinkIndex, value) {
  const sink = sinkEdit(flowIndex, sinkIndex);
  if (sink) sink.name = value;
}

function sinkLocation(flowIndex, sinkIndex) {
  const sink = templateSinks.value[flowIndex]?.[sinkIndex];
  if (!sink) return "";
  return composeSinkLocation(
    assignments.value[flowIndex]?.sinks?.[sinkIndex]?.folder,
    sinkName(flowIndex, sinkIndex),
    sink.sink_type,
  );
}

// Unlike the template wizard — where a blank folder means "let the backend
// place it" — a template run must supply an explicit path for every file sink
// (session_config._locations_by_index rejects a create that omits one). So an
// unresolved destination here is a blocker, not a default.
function flowSinksResolved(flowIndex) {
  return (templateSinks.value[flowIndex] ?? []).every(
    (sink, sinkIndex) => !isFileSink(sink.sink_type) || Boolean(sinkLocation(flowIndex, sinkIndex)),
  );
}

function flowReady(flowIndex) {
  const assignment = assignments.value[flowIndex];
  return Boolean(assignment?.deviceConfigId) && flowSinksResolved(flowIndex);
}

// A folder column is never wide enough for an absolute path, and plain ellipsis
// truncates the wrong end. The trailing segments are what name a destination.
const FOLDER_TAIL_BUDGET = 24;

function shortFolder(path) {
  if (!path) return "";
  const separator = path.includes("\\") ? "\\" : "/";
  const segments = path.split(separator).filter(Boolean);
  if (segments.length <= 2) return path;
  const tail = segments.slice(-2).join(separator);
  return `…${separator}${tail.length <= FOLDER_TAIL_BUDGET ? tail : segments[segments.length - 1]}`;
}

function openFolderPicker(flowIndex, sinkIndex) {
  folderPickerTarget.value = { flowIndex, sinkIndex };
}

const folderPickerFolder = computed(() => {
  const target = folderPickerTarget.value;
  if (!target) return "";
  return assignments.value[target.flowIndex]?.sinks?.[target.sinkIndex]?.folder ?? "";
});

async function chooseFolder(path) {
  const target = folderPickerTarget.value;
  if (target) {
    const sink = assignments.value[target.flowIndex]?.sinks?.[target.sinkIndex];
    if (sink) sink.folder = path;
  }
  folderPickerTarget.value = null;
  await verifyOutputFolders().catch(() => {});
}

function currentOutputFolders() {
  return assignments.value.flatMap((assignment) =>
    (templateSinks.value[assignment.flowIndex] ?? []).flatMap((sink, sinkIndex) =>
      isFileSink(sink.sink_type)
        ? [assignment.sinks?.[sinkIndex]?.folder]
        : [],
    ),
  );
}

async function verifyOutputFolders() {
  try {
    await validateOutputFolders(currentOutputFolders(), browseDirectories);
    folderValidationError.value = "";
  } catch (error) {
    folderValidationError.value = describeError(error, "An output folder is unavailable on the session host.");
    throw error;
  }
}

// The backend refuses to overwrite an explicit path but proposes a free one
// alongside the refusal (SinkLocationExists.suggested_location). Applying it
// writes back through the same folder + name fields the operator edits, so what
// they see afterwards is still the whole truth about where the file goes.
function applySuggestedLocation() {
  const conflict = collision.value;
  if (!conflict) return;
  const sink = assignments.value[conflict.flowIndex]?.sinks?.[conflict.sinkIndex];
  const sinkType = templateSinks.value[conflict.flowIndex]?.[conflict.sinkIndex]?.sink_type;
  if (!sink || !sinkType) return;
  const folder = outputFolder(conflict.suggested);
  if (folder) sink.folder = folder;
  const file = conflict.suggested.split(/[\\/]/).pop() ?? "";
  sink.name = file.toLowerCase().endsWith(`.${sinkType}`)
    ? file.slice(0, -(sinkType.length + 1))
    : file;
  collision.value = null;
  submitError.value = "";
}

// --- Gating -----------------------------------------------------------------

const unassignedCount = computed(
  () => assignments.value.filter((assignment) => !assignment.deviceConfigId).length,
);
const unresolvedSinkCount = computed(
  () => assignments.value.filter((assignment) => !flowSinksResolved(assignment.flowIndex)).length,
);
const scheduleIncomplete = computed(() => runMode.value === "schedule" && !scheduleAt.value);

const submitDisabled = computed(
  () =>
    loadState.value !== "ready" ||
    submitting.value ||
    stale.value ||
    !assignments.value.length ||
    unassignedCount.value > 0 ||
    unresolvedSinkCount.value > 0 ||
    Boolean(folderValidationError.value) ||
    scheduleIncomplete.value,
);

// Why Start is disabled, in the operator's terms, ordered by what they should
// deal with first rather than by how the checks happen to be written.
const blockedReason = computed(() => {
  if (!submitDisabled.value || loadState.value !== "ready" || submitting.value) return "";
  if (stale.value) return "";
  if (unassignedCount.value) {
    return `Assign a device to ${unassignedCount.value} more stream${unassignedCount.value === 1 ? "" : "s"}.`;
  }
  if (unresolvedSinkCount.value) return "Every file sink needs a folder and a filename.";
  if (folderValidationError.value) return folderValidationError.value;
  if (scheduleIncomplete.value) return "Pick a start time to schedule this run.";
  return "";
});

const submitLabel = computed(() => {
  if (submitState.value === "creating") return "Creating session…";
  if (runMode.value === "schedule") return "Schedule session";
  return "Start session";
});

// --- Load -------------------------------------------------------------------

function resetAssignments(plan) {
  assignments.value = flows.value.map((_, flowIndex) => ({
    flowIndex,
    deviceConfigId: plan?.assignments?.find((item) => item.flow_index === flowIndex)?.device_config_id ?? null,
    // Seeded from the template's own destination when it names one, else the
    // host's output root — a run cannot proceed without a folder, so starting
    // from a real one is the difference between confirming and hunting.
    sinks: (templateSinks.value[flowIndex] ?? []).map((sink) => ({
      folder: sink.sink_folder || defaultOutputFolder.value,
      name: "",
    })),
  }));
}

function returnToCurrentTemplate(guidance = "") {
  stale.value = true;
  submitError.value = guidance || templateStateHint(template.value) || "This template revision can no longer start a run.";
}

async function rescanDevices() {
  scanState.value = "scanning";
  scanError.value = "";
  try {
    const pool = await loadDevicePool();
    devices.value = pool.devices;
    scanState.value = "ready";
  } catch (reason) {
    // The previous list stays on screen: a live scan takes a couple of seconds,
    // and blanking the table would make an already-assigned device flicker out.
    scanState.value = "error";
    scanError.value = reason?.problem?.detail ?? reason?.message ?? "Device scan is unavailable.";
  }
}

async function load() {
  loadState.value = "loading";
  loadError.value = "";
  submitError.value = "";
  folderValidationError.value = "";
  stale.value = false;
  collision.value = null;
  try {
    const selected = await loadSessionTemplate(props.templateId);
    template.value = selected;
    loadedRevision.value = selected;
    if (selected.state !== "ACTIVE") {
      loadState.value = "ready";
      returnToCurrentTemplate(templateStateHint(selected));
      return;
    }
    // Deliberately WITHOUT the device pool. The assignment planner runs its own
    // device discovery, and the two scans contend: issued concurrently, the
    // planner request never returns and the dialog sits on "Preparing template
    // run…" forever. Everything batched here is scan-free.
    const [planResult, suggestionResult, folderResult, deviceTemplateResult] = await Promise.allSettled([
      loadAssignmentPlan(selected.reference || selected.templateId),
      loadSessionNameSuggestion(selected.templateId),
      browseDirectories(),
      loadDeviceTemplates(),
    ]);
    if (planResult.status === "rejected") throw planResult.reason;
    assignmentPlan.value = planResult.value;
    nameSuggestion.value = suggestionResult.status === "fulfilled" ? suggestionResult.value : "";
    if (folderResult.status === "fulfilled") defaultOutputFolder.value = folderResult.value.path ?? "";
    deviceTemplates.value = deviceTemplateResult.status === "fulfilled" ? deviceTemplateResult.value : [];
    resetAssignments(planResult.value);
    // Validate template-seeded paths during preparation so an unavailable
    // destination disables Start immediately, before the operator submits.
    await verifyOutputFolders().catch(() => {});
    loadState.value = "ready";
    // Now that the planner has answered, discover the pool — not awaited, so the
    // form paints immediately and the device tables fill in behind their own
    // "Scanning…" state rather than holding the whole dialog back.
    rescanDevices();
  } catch (error) {
    template.value = null;
    loadError.value = describeError(error, "This template run could not be prepared.");
    loadState.value = "error";
  }
}

// An unconfigured compatible row is configured from this stream's template,
// so the operator chooses hardware without recreating its settings.
async function configureDevice(flowIndex, device) {
  const template = deviceTemplateForFlow(flowIndex);
  const hardwareId = device.hardwareId;
  const port = device.port;
  if (!template || !hardwareId || !port) {
    scanError.value = "This device cannot be configured because the stream template or hardware details are unavailable.";
    return;
  }
  const key = `${flowIndex}:${hardwareId}`;
  if (configuringHardware.has(key)) return;
  configuringHardware.add(key);
  scanError.value = "";
  try {
    await createDeviceConfigFromTemplate({
      template_name: template.name,
      hardware_id: hardwareId,
      port,
      nickname: device.nickname,
    });
    await rescanDevices();
    const configured = devices.value.find(
      (candidate) =>
        candidate.hardwareId === hardwareId &&
        candidate.type === requiredDeviceType(flowIndex) &&
        isDeviceSelectable(candidate),
    );
    if (configured) {
      const assignment = assignments.value[flowIndex];
      if (assignment) assignment.deviceConfigId = configured.id;
    } else {
      scanError.value = "The device was configured, but it was not available to assign after the rescan.";
    }
  } catch (error) {
    scanError.value = describeError(error, "The selected device could not be configured from this stream's template.");
  } finally {
    configuringHardware.delete(key);
  }
}

// --- Submit -----------------------------------------------------------------

async function revisionIsCurrent() {
  const current = await loadSessionTemplate(props.templateId);
  template.value = current;
  if (!templateRevisionChanged(loadedRevision.value, current)) return true;
  returnToCurrentTemplate(templateStateHint(current));
  return false;
}

function payload() {
  return buildTemplateRunPayload({
    template: loadedRevision.value,
    // The composed name is passed rather than the raw field: a blank field
    // means "use the generated default", and the default is what the operator
    // has been reading in the placeholder all along.
    assignments: assignments.value.map((assignment) => ({
      flowIndex: assignment.flowIndex,
      deviceConfigId: assignment.deviceConfigId,
      sinks: assignment.sinks.map((sink, sinkIndex) => ({
        folder: sink.folder,
        name: sinkName(assignment.flowIndex, sinkIndex),
      })),
    })),
    name: name.value,
    experimentId: experimentId.value,
    notes: notes.value,
    scheduleAt: runMode.value === "schedule" ? scheduleAt.value : "",
  });
}

// A refused path comes back with the coordinates the client submitted, because
// a template run addresses sinks positionally and the operator never sees a
// sink name to match on.
function readCollision(problem) {
  if (problem?.code !== "sink_location_exists" || !problem.suggested_location) return null;
  if (!Number.isInteger(problem.flow_index) || !Number.isInteger(problem.sink_index)) return null;
  return {
    flowIndex: problem.flow_index,
    sinkIndex: problem.sink_index,
    suggested: problem.suggested_location,
  };
}

async function submit() {
  if (submitDisabled.value) return;
  submitError.value = "";
  collision.value = null;
  submitState.value = "creating";
  try {
    // The template may have drifted after this form loaded. Check immediately
    // before create; the backend repeats the same ID/hash check atomically.
    if (!(await revisionIsCurrent())) return;
    // Template defaults can name a drive or folder that disappeared after the
    // template was authored. The picker validates operator choices, but seeded
    // values need the same host-side check. This gate deliberately precedes
    // run creation so an unusable destination cannot reach the atomic command.
    await verifyOutputFolders();
    // One command either starts now or stores the future schedule. A definite
    // pre-dispatch failure returns here without creating a session.
    const requestPayload = payload();
    const fingerprint = JSON.stringify(requestPayload);
    if (requestIdentity.value.fingerprint !== fingerprint) {
      requestIdentity.value = {
        fingerprint,
        key: globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`,
      };
    }
    const result = await createTemplateRun(requestPayload, {
      idempotencyKey: requestIdentity.value.key,
    });
    submitState.value = "complete";
    emit("created", String(result.id));
  } catch (error) {
    if (/template/i.test(error?.problem?.code ?? "")) {
      submitState.value = "stale";
      stale.value = true;
      submitError.value = describeError(error, "The template changed before this run could be created.");
      return;
    }
    submitState.value = "error";
    collision.value = readCollision(error?.problem);
    submitError.value = describeError(error, "The run could not be created.");
  } finally {
    if (submitState.value === "creating") submitState.value = "idle";
  }
}

// Esc closes the dialog, but only when it is the frontmost one — otherwise
// dismissing the folder picker would take the whole run form with it.
function onKeydown(event) {
  if (event.key !== "Escape") return;
  if (folderPickerTarget.value) return;
  emit("cancel");
}

onMounted(() => {
  load();
  window.addEventListener("keydown", onKeydown);
});
onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown));
watch(() => props.templateId, load);
</script>

<template>
  <div class="dialog-backdrop" role="presentation" @mousedown.self="emit('cancel')">
    <section class="dialog start-run" role="dialog" aria-modal="true" aria-labelledby="start-run-title">
      <header>
        <div>
          <h2 id="start-run-title">Start a new session</h2>
        </div>
        <button class="icon-button" type="button" aria-label="Close dialog" @click="emit('cancel')"><X :size="19" /></button>
      </header>

      <div class="dialog__content">
        <p v-if="loadState === 'loading'" class="empty-state" aria-busy="true">Preparing template run…</p>
        <div v-else-if="loadError" class="form-notice" role="alert">
          <AlertTriangle :size="18" />
          <span>{{ loadError }}</span>
          <BaseButton variant="secondary" @click="load"><RefreshCw :size="16" /> Retry</BaseButton>
        </div>

        <template v-else-if="template">
          <section class="run-banner" aria-label="Selected template">
            <div>
              <span class="section-kicker">Selected template</span>
              <h3>{{ template.name }}</h3>
              <p>
                {{ flows.length }} stream{{ flows.length === 1 ? "" : "s" }} ·
                {{ flows.reduce((total, flow) => total + (flow.sinks?.length ?? 0), 0) }} sinks ·
                {{ template.content?.policy || "No recovery policy" }}
              </p>
            </div>
            <StatusBadge :value="stale ? 'Stale' : 'Ready'" compact />
          </section>

          <section class="run-section">
            <div class="section-heading">
              <div><span class="section-kicker">Run details</span><h3>Optional metadata</h3></div>
              <p>Blank values use backend defaults.</p>
            </div>
            <div class="form-grid metadata-grid">
              <label class="field">
                <span>Session label (optional)</span>
                <input v-model="name" :placeholder="nameSuggestion || 'Generated after create'" />
              </label>
              <label class="field">
                <span>Experiment ID (optional)</span>
                <input v-model="experimentId" placeholder="No experiment" />
              </label>
              <label class="field field--wide">
                <span>Notes (optional)</span>
                <textarea v-model="notes" placeholder="Add a note for this run…" />
              </label>
            </div>
          </section>

          <p v-for="warning in assignmentPlan?.warnings ?? []" :key="warning" class="form-notice">
            <AlertTriangle :size="18" /> {{ warning }}
          </p>

          <!-- One run section owns every template flow. Each flow is a sub-card:
               the device that fills it, then where that device's sinks write.
               Sink type, order and count come from the frozen revision and are
               shown, never offered. -->
          <section class="run-section">
            <div class="section-heading">
              <div><span class="section-kicker">Dataflow Details</span><h3>Devices and sinks connection</h3></div>
            </div>

            <div class="flow-stack">
              <article
                v-for="assignment in assignments"
                :key="assignment.flowIndex"
                class="flow-card"
                :aria-labelledby="`stream-${assignment.flowIndex}-title`"
              >
                <div class="flow-card__heading">
                  <div>
                    <div class="flow-card__kicker-row">
                      <h4 :id="`stream-${assignment.flowIndex}-title`" class="section-kicker">
                        Stream {{ assignment.flowIndex + 1 }}
                      </h4>
                      <StatusBadge compact :value="flowReady(assignment.flowIndex) ? 'Ready' : 'Needs setup'" />
                    </div>
                    <strong
                      v-if="flows[assignment.flowIndex]?.nickname && flows[assignment.flowIndex]?.nickname !== `Stream ${assignment.flowIndex + 1}`"
                      class="flow-nickname"
                    >
                      {{ flows[assignment.flowIndex].nickname }}
                    </strong>
                    <p>Requires <code>{{ flows[assignment.flowIndex]?.device_template_path || "any device" }}</code></p>
                  </div>
                </div>

                <DeviceScanTable
                  :group="`flow-${assignment.flowIndex}`"
                  :devices="candidateDevices(assignment.flowIndex)"
                  :selected="assignment.deviceConfigId == null ? [] : [assignment.deviceConfigId]"
                  :annotate="annotateFor(assignment.flowIndex)"
                  :selectable="isPreferenceSelectable"
                  :scanning="scanState === 'scanning'"
                  :scan-error="scanState === 'error' ? scanError : ''"
                  empty-message="No free device is available for this stream."
                  @toggle="assignDevice(assignment.flowIndex, $event)"
                  @configure="configureDevice(assignment.flowIndex, $event)"
                  @rescan="rescanDevices"
                >
                  <template #heading><h4>Pick a device for this stream</h4></template>
                </DeviceScanTable>

                <h4 class="sink-heading">Sink destinations</h4>
                <p class="sink-caption">
                  Sink types come from the template and cannot change here. Every file sink needs
                  a folder and a filename — a template run writes to paths you choose, so nothing
                  is placed automatically.
                </p>
                <div class="table-wrap sink-table-wrap">
                  <table class="data-table sink-table">
                    <thead><tr><th>Sink type</th><th>Name</th><th>Folder</th></tr></thead>
                    <tbody>
                      <tr v-if="!templateSinks[assignment.flowIndex]?.length"><td colspan="3">This stream has no sinks.</td></tr>
                      <tr v-for="(sink, sinkIndex) in templateSinks[assignment.flowIndex] ?? []" :key="sinkIndex">
                        <!-- Locked by the template: rendered as a value, not a
                             control, so there is nothing to try and fail to change. -->
                        <td><span class="sink-locked">{{ sink.sink_type }}</span></td>
                        <td>
                          <div v-if="isFileSink(sink.sink_type)" class="sink-name">
                            <input
                              :value="sinkEdit(assignment.flowIndex, sinkIndex)?.name ?? ''"
                              class="sink-control"
                              aria-label="Sink filename"
                              :placeholder="defaultSinkName(assignment.flowIndex, sinkIndex) || 'Assign a device first'"
                              :title="sinkName(assignment.flowIndex, sinkIndex)"
                              @input="setSinkName(assignment.flowIndex, sinkIndex, $event.target.value)"
                            />
                            <span class="sink-extension">.{{ sink.sink_type }}</span>
                          </div>
                          <span v-else class="sink-muted">{{ sink.sink_name || sink.sink_type }}</span>
                        </td>
                        <td>
                          <button
                            v-if="isFileSink(sink.sink_type)"
                            type="button"
                            class="sink-control sink-folder-tile"
                            :class="{ 'sink-folder-tile--empty': !sinkEdit(assignment.flowIndex, sinkIndex)?.folder }"
                            :aria-label="`Change folder for ${sink.sink_type} sink`"
                            :title="sinkLocation(assignment.flowIndex, sinkIndex) || 'Choose a folder for this sink'"
                            @click="openFolderPicker(assignment.flowIndex, sinkIndex)"
                          >
                            <span class="sink-folder-path">{{ shortFolder(sinkEdit(assignment.flowIndex, sinkIndex)?.folder) || "Choose a folder…" }}</span>
                            <FolderPen :size="16" class="sink-folder-icon" />
                          </button>
                          <span v-else class="sink-muted">No file output</span>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </article>
            </div>
          </section>

          <section class="run-section">
            <div class="section-heading"><div><span class="section-kicker">Timing</span><h3>Create and start</h3></div></div>
            <fieldset class="run-mode">
              <label><input v-model="runMode" type="radio" value="start" /><span><strong>Start now</strong><small>Validate and start this run in one request.</small></span></label>
              <label><input v-model="runMode" type="radio" value="schedule" /><span><strong>Schedule for later</strong><small>Save one future run without claiming hardware now.</small></span></label>
            </fieldset>
            <label v-if="runMode === 'schedule'" class="field schedule-field">
              <span>Scheduled start</span>
              <input v-model="scheduleAt" type="datetime-local" />
            </label>
            <fieldset v-if="runMode === 'schedule'" class="run-mode">
              <legend>Device availability at start time</legend>
              <p>The preferred device will be used when available. Otherwise, the scheduler selects the closest free compatible device; if none exists, it cancels the run.</p>
            </fieldset>
          </section>

          <div v-if="submitError" class="form-notice" role="alert">
            <AlertTriangle :size="18" />
            <span>
              <strong>Run not created</strong>
              <span class="notice-detail">{{ submitError }}</span>
            </span>
            <button v-if="collision" type="button" class="table-action" @click="applySuggestedLocation">
              Use {{ collision.suggested }}
            </button>
          </div>
        </template>
      </div>

      <footer>
        <div class="run-footer__messages">
          <div v-if="blockedReason" class="run-footer__warning" role="alert">
            <AlertTriangle :size="16" />
            <span>{{ blockedReason }}</span>
          </div>
        </div>
        <div class="run-footer__actions">
          <BaseButton variant="secondary" @click="emit('cancel')">Cancel</BaseButton>
          <BaseButton :disabled="submitDisabled" @click="submit">{{ submitLabel }}</BaseButton>
        </div>
      </footer>
    </section>
  </div>

  <!-- Siblings rather than children: both render their own fixed backdrop, and
       nesting them inside this one would put them in its stacking context and
       add stray cells to its centering grid. -->
  <FolderPickerDialog
    v-if="folderPickerTarget"
    :model-value="folderPickerFolder"
    @select="chooseFolder"
    @close="folderPickerTarget = null"
  />
</template>

<style scoped>
/* Wider than the 600px default: this dialog carries a device table and a sink
   table per stream, and the shared width would put both under a scrollbar. */
.start-run {
  width: min(1040px, 100%);
}
/* The content is the scrolling region, so it gets more of the viewport than the
   shared 60vh — a two-stream template otherwise scrolls in a letterbox. */
.start-run .dialog__content {
  display: grid;
  max-height: min(72vh, 900px);
  gap: var(--space-4);
  background: var(--surface-page);
}
.start-run > header {
  align-items: center;
}
.section-kicker {
  color: var(--primary);
  font-size: var(--fs-xs);
  font-weight: 800;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}
.run-banner {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4);
  border: 1px solid var(--border-card);
  border-left: 4px solid var(--accent);
  border-radius: var(--radius-md);
  background: var(--white);
}
.run-banner h3 {
  margin-top: var(--space-1);
  color: var(--ink);
  font-size: var(--fs-lg);
}
.run-banner p,
.section-heading p,
.sink-caption {
  margin-top: var(--space-1);
  color: var(--muted);
  font-size: var(--fs-sm);
}
.run-section {
  padding: var(--space-4);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-md);
  background: var(--white);
}
.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}
.section-heading h3 {
  margin-top: var(--space-1);
  color: var(--ink);
  font-size: var(--fs-md);
}
.section-heading code {
  overflow-wrap: anywhere;
}
.metadata-grid {
  max-width: none;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.flow-stack {
  display: grid;
  gap: var(--space-4);
}
.flow-card {
  padding: var(--space-4);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-md);
  background: var(--sage-50);
}
.flow-card__heading {
  margin-bottom: var(--space-4);
}
.flow-card__kicker-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.flow-card__kicker-row .section-kicker,
.flow-card h4 {
  margin: 0;
}
.flow-card__kicker-row .section-kicker {
  color: var(--ink-900);
  font-size: var(--fs-xs);
}
.flow-card h4:not(.section-kicker) {
  color: var(--ink);
  font-size: var(--fs-sm);
}
.flow-nickname {
  display: block;
  margin-top: var(--space-1);
  color: var(--ink);
  font-size: var(--fs-md);
}
.flow-card__heading p {
  margin-top: var(--space-1);
  color: var(--muted);
  font-size: var(--fs-sm);
}
.flow-card :deep(.device-scan .table-wrap),
.sink-table-wrap {
  border: 1px solid var(--sage-50);
  border-radius: var(--radius-md);
  background: var(--surface-card);
}
.flow-card :deep(.device-scan .data-table),
.sink-table {
  margin-top: 0;
}
.flow-card :deep(.device-scan th),
.sink-table th {
  background: var(--green-800);
  color: var(--sage-50);
}
.flow-card :deep(.device-scan td),
.sink-table td {
  border-top: 1px solid var(--sage-200);
}
.flow-card :deep(.device-scan tbody tr:nth-child(even)),
.sink-table tbody tr:nth-child(even) {
  background: var(--sage-50);
}
.sink-heading {
  margin-top: var(--space-4) !important;
}
.sink-caption {
  margin-bottom: var(--space-3);
}
/* The sink table holds an absolute path, which under `table-layout: auto` sizes
   its column to the whole string and forces the table past the dialog. Fixed
   layout makes the declared widths authoritative, which is also what lets the
   ellipsis in .sink-folder-path engage. */
.sink-table {
  width: 100%;
  min-width: 0;
  table-layout: fixed;
}
.sink-table th,
.sink-table td {
  padding: var(--space-3) var(--space-2);
}
.sink-table th:nth-child(1),
.sink-table td:nth-child(1) {
  width: 14%;
}
.sink-table th:nth-child(2),
.sink-table td:nth-child(2) {
  width: 40%;
}
.sink-table th:nth-child(3),
.sink-table td:nth-child(3) {
  width: 46%;
}
/* Template-owned, so it reads as a label rather than a disabled control — a
   greyed <select> invites the click it would then refuse. */
.sink-locked {
  display: inline-block;
  padding: 0.15rem var(--space-2);
  color: var(--muted);
  border-radius: var(--radius-pill);
  background: var(--surface-sage);
  font-size: var(--fs-xs);
  font-weight: 700;
  text-transform: uppercase;
}
.sink-muted {
  color: var(--muted);
  font-size: var(--fs-sm);
}
.sink-control {
  width: 100%;
  min-width: 0;
  min-height: 36px;
  padding: var(--space-2) var(--space-3);
  color: var(--text-body);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-md);
  background: var(--surface-sage);
  font-size: var(--fs-sm);
}
/* Name + extension read as one field: the input carries the editable stem and
   the suffix sits inside the same box, greyed, so the row shows the whole
   filename without letting anyone type an extension the template contradicts. */
.sink-name {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding-right: var(--space-3);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-md);
  background: var(--surface-sage);
}
.sink-name .sink-control {
  border: 0;
  background: none;
}
.sink-name:focus-within {
  border-color: var(--primary, var(--border-card));
}
.sink-extension {
  color: var(--muted);
  font-size: var(--fs-sm);
  white-space: nowrap;
}
.sink-folder-tile {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  text-align: left;
  cursor: pointer;
}
/* A run cannot start without this, so an empty tile is a blocker rather than an
   invitation — amber says so before Start has to. */
.sink-folder-tile--empty {
  color: var(--warning);
  border-color: var(--warning);
}
.sink-folder-tile:hover,
.sink-folder-tile:focus-visible {
  border-color: var(--primary, var(--border-card));
  background: var(--sage-50);
}
.sink-folder-path {
  flex: 1 1 auto;
  overflow: hidden;
  min-width: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sink-folder-icon {
  flex: 0 0 auto;
  color: var(--muted);
}
.run-mode {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
  padding: 0;
  border: 0;
}
.run-mode label {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-md);
  cursor: pointer;
}
.run-mode label:has(input:checked) {
  border-color: var(--accent);
  background: var(--sage-50);
  box-shadow: inset 3px 0 0 var(--accent);
}
.run-mode input {
  margin-top: 0.18rem;
  accent-color: var(--accent);
}
.run-mode span {
  display: grid;
  gap: var(--space-1);
}
.run-mode small {
  color: var(--muted);
  font-size: var(--fs-xs);
}
.schedule-field {
  max-width: 24rem;
  margin-top: var(--space-4);
}
.notice-detail {
  display: block;
  margin-top: var(--space-1);
}
.run-result {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  color: var(--success);
  border: 1px solid var(--sage-300);
  border-radius: var(--radius-md);
  background: var(--sage-50);
  font-size: var(--fs-sm);
}
.start-run > footer {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}
.run-footer__messages {
  display: grid;
  flex: 1 1 auto;
  min-width: 0;
  gap: var(--space-2);
}
.run-footer__warning {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-3);
  color: #9f5c08;
  border: 1px solid #e6c27a;
  border-radius: var(--radius-md);
  background: #fff9e8;
  font-size: var(--fs-xs);
}
.run-footer__warning svg {
  flex: 0 0 auto;
}
.run-footer__actions {
  display: flex;
  flex: 0 0 auto;
  gap: var(--space-3);
}
.run-footnote {
  color: var(--muted);
  font-size: var(--fs-xs);
}
@media (max-width: 760px) {
  .metadata-grid {
    grid-template-columns: 1fr;
  }
  .run-mode {
    grid-template-columns: 1fr;
  }
  .start-run > footer {
    align-items: stretch;
    flex-direction: column;
  }
  .run-footer__actions {
    justify-content: flex-end;
  }
}
</style>
