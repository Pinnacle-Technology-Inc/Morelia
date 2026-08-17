<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import {
  AlertTriangle,
  ArrowLeft,
  ExternalLink,
  FlaskConical,
  Play,
  Shield,
  StopCircle,
} from "@lucide/vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import CollapsibleSection from "../components/CollapsibleSection.vue";
import CommandErrorDialog from "../components/CommandErrorDialog.vue";
import GuardedDialog from "../components/GuardedDialog.vue";
import RatRunIndicator from "../components/RatRunIndicator.vue";
import SessionNotesList from "../components/SessionNotesList.vue";
import SessionFlowBar from "../components/SessionFlowBar.vue";
import SessionDiagnosticLog from "../components/SessionDiagnosticLog.vue";
import SessionTimeline from "../components/SessionTimeline.vue";
import StatusBadge from "../components/StatusBadge.vue";
import TabBar from "../components/TabBar.vue";
import { normalizeSession, stopSession } from "../session-api";
import { loadSessionActivity } from "../session-activity-api";
import { loadSessionDetail } from "../session-detail-api";
import {
  createSessionEventStream,
  isSessionActivityEvent,
  SessionEventState,
} from "../session-events";
import { createSessionNote, loadSessionNotes, updateSessionNote } from "../session-notes-api";
import { buildActivityTimeline, buildSessionTimeline, formatGapWindow as displayGapWindow } from "../session-timeline";
import { formatCentralTimestamp } from "../datetime";
import {
  deriveFlowStatus,
  deriveRatState,
  deriveStreamRows,
  isOutboxUnproven,
} from "../session-flow-status";
import { isRunningLifecycle } from "../session-utils";
import { canRunTemplate, loadDeviceTemplates, loadSessionTemplate, templateStateHint } from "../templates-api";

// `session` is an OPTIONAL fast-path only: the catalog row, when the operator
// arrived from the sessions list. This page resolves everything it needs from
// `sessionId` alone via GET /sessions/<id>/status, whose response is a superset
// of the catalog row. That is what lets a just-created session be deep-linked
// straight from the Create wizard, before any list has been refetched.
const props = defineProps({
  session: { type: Object, default: null },
  sessionId: { type: [String, Number], required: true },
});
const emit = defineEmits(["back", "start-another-run", "state-changed"]);

const activeTab = ref("overview");
const dialog = ref(null);
const detail = ref(null);
const detailState = ref("loading");
const detailError = ref("");
const commandError = ref("");
const commandProblem = ref(null);
const commandBusy = ref(false);
const sourceTemplate = ref(null);
const sourceTemplateState = ref("idle");
const sourceTemplateError = ref("");
const sourceDeviceTemplates = ref([]);
const sourceDeviceTemplatesState = ref("idle");
const sourceDeviceTemplatesError = ref("");
const notes = ref([]);
const notesState = ref("idle");
const notesError = ref("");
const noteEditor = ref(null);
const noteBody = ref("");
const noteShowTimestamp = ref(false);
const noteBusy = ref(false);
const noteSaveError = ref("");
const activity = ref({ state: SessionEventState.IDLE, events: [], error: null });
const activityRecords = ref([]);
const activityRecordsState = ref("loading");
const activityRecordsError = ref("");
// Optimistic lifecycle from a just-issued command, shown until the refetch that
// follows it lands. Cleared by refreshDetail() so the server always wins.
const pendingLifecycle = ref(null);
let eventStream;
let pollTimer = null;
let activityRefreshTimer = null;
let detailRefreshTimer = null;
let sourceTemplateRequest = 0;
let resolvedSourceTemplateId = null;

// Shown for the one round-trip between mounting on a bare id (deep link from the
// Create wizard) and /status answering. `lifecycle: "Unknown"` is deliberate —
// see RESTING_HEADLINE in session-flow-status.js.
const PLACEHOLDER_SESSION = Object.freeze({
  id: null,
  name: "Session",
  lifecycle: "Unknown",
  health: "Unknown",
  experiment: null,
  scheduledTime: null,
  deviceCount: 0,
  streamCount: 0,
  sinkCount: 0,
  watchdog: "Unknown",
  phase: null,
  policy: null,
  deviceFlows: [],
  createdAt: null,
  isOwner: true,
});

// Everything the page renders comes from here. Precedence is deliberate:
// /status wins over the catalog row the moment it lands, because the row can be
// an arbitrarily stale snapshot from whenever the list was last fetched.
// normalizeSession() is reused rather than re-deriving these fields, so the list
// view and this page can never drift apart in how they label a session.
const view = computed(() => {
  const snapshot = detail.value;
  if (snapshot?.session) {
    const merged = normalizeSession(snapshot.session, {
      health: snapshot.health,
      phase: snapshot.phase,
    });
    return {
      ...merged,
      // normalizeSession() can only infer watchdog state from lifecycle; the
      // detail endpoint reports it directly, so prefer the real value.
      watchdog: snapshot.watchdog_state ? formatStatus(snapshot.watchdog_state) : merged.watchdog,
    };
  }
  return props.session ?? PLACEHOLDER_SESSION;
});

// STOPPED was the old intermediate state before an explicit Complete command.
// Stopping is terminal now, but this compatibility mapping keeps historical or
// briefly stale payloads from leaking the retired lifecycle into the page.
const lifecycle = computed(() => {
  const value = pendingLifecycle.value ?? view.value.lifecycle;
  return String(value).toLowerCase() === "stopped" ? "Completed" : value;
});

// Session provenance is immutable history. The registry resource below is a
// separate, current-state lookup used only to decide whether a NEW child run can
// be created; the frozen snapshot is never used to restart this session.
const sourceTemplateId = computed(() => detail.value?.session?.source_template_id ?? null);
const sourceTemplateSnapshot = computed(() => detail.value?.session?.source_template_snapshot ?? null);
const sourceSnapshotContent = computed(() => sourceTemplateSnapshot.value?.content ?? null);
const sourceInformationContent = computed(() => sourceSnapshotContent.value ?? sourceTemplate.value?.content ?? null);
const sourceInformationFlows = computed(() =>
  Array.isArray(sourceInformationContent.value?.device_flows) ? sourceInformationContent.value.device_flows : [],
);
const sourceInformationSinkCount = computed(() =>
  sourceInformationFlows.value.reduce(
    (total, flow) => total + (Array.isArray(flow?.sinks) ? flow.sinks.length : 0),
    0,
  ),
);
const sourceDeviceTemplatesByPath = computed(() => new Map(
  sourceDeviceTemplates.value.map((item) => [normalizeTemplatePath(item?.file_path), item]),
));
const sourceFlowDetails = computed(() => sourceInformationFlows.value.map((flow, index) => {
  const path = typeof flow?.device_template_path === "string" ? flow.device_template_path : "";
  const linkedTemplate = sourceDeviceTemplatesByPath.value.get(normalizeTemplatePath(path));
  const parameters = linkedTemplate?.content?.parameters;
  const stats = [];
  const deviceType = linkedTemplate?.type ?? linkedTemplate?.content?.type;
  if (deviceType != null) stats.push({ label: "Device type", value: formatTemplateStatValue(deviceType) });
  if (parameters && typeof parameters === "object") {
    for (const [key, value] of Object.entries(parameters)) {
      if (value != null) stats.push({ label: formatTemplateStatLabel(key), value: formatTemplateStatValue(value) });
    }
  }
  if (flow?.hardware_id != null) stats.push({ label: "Hardware ID", value: formatTemplateStatValue(flow.hardware_id) });
  if (flow?.port != null) stats.push({ label: "Port", value: formatTemplateStatValue(flow.port) });

  const expectedHash = flow?.device_template_content_hash ?? null;
  const observedHash = linkedTemplate?.content_hash ?? null;
  return {
    key: `${path || "stream"}-${index}`,
    title: flow?.nickname || path.split("/").pop()?.replace(/\.toml$/i, "") || `Stream ${index + 1}`,
    path,
    expectedHash,
    revisionMatches: Boolean(expectedHash && observedHash && expectedHash === observedHash),
    revisionDiffers: Boolean(expectedHash && observedHash && expectedHash !== observedHash),
    stats,
    statsUnavailable: linkedTemplate
      ? ""
      : sourceDeviceTemplatesState.value === "loading"
        ? "Loading device-template stats…"
        : sourceDeviceTemplatesError.value || "Linked device template was not found in the current catalog.",
    sinks: (Array.isArray(flow?.sinks) ? flow.sinks : []).map((sink, sinkIndex) => ({
      key: `${index}-${sinkIndex}`,
      name: sink?.sink_name || sink?.sink_type || `Sink ${sinkIndex + 1}`,
      type: sink?.sink_type ?? "Unavailable",
      location: sink?.sink_location ?? null,
      parameters: Object.entries(sink?.sink_parameters ?? {}),
    })),
  };
}));
const sourceSnapshotJson = computed(() => JSON.stringify(sourceTemplateSnapshot.value, null, 2));
const hasSourceProvenance = computed(() => Boolean(
  sourceTemplateId.value ||
  sourceTemplateSnapshot.value ||
  detail.value?.session?.source_template_name ||
  detail.value?.session?.source_template_ref ||
  detail.value?.session?.source_template_hash
));
const sourceTemplateRunnable = computed(() =>
  lifecycle.value === "Completed" &&
  sourceTemplateState.value === "live" &&
  Boolean(sourceTemplate.value?.templateId) &&
  canRunTemplate(sourceTemplate.value),
);
const sourceTemplateGuidance = computed(() => {
  if (!sourceTemplateId.value) {
    return "This legacy run has no source template identity. Its stored provenance remains available, but another run cannot be launched from it.";
  }
  if (sourceTemplateState.value === "loading") {
    return "Checking the source template's current registry state…";
  }
  if (sourceTemplateState.value === "unavailable") {
    return sourceTemplateError.value || "The source template could not be resolved. Restore or reconcile it before starting another run.";
  }
  if (sourceTemplateState.value === "live") {
    if (canRunTemplate(sourceTemplate.value)) {
      if (lifecycle.value !== "Completed") {
        return "This session uses the frozen revision below. The current source revision is ACTIVE; another run becomes available after this session completes.";
      }
      return "The source revision is currently ACTIVE. Starting again creates a new child run and leaves this run unchanged.";
    }
    return templateStateHint(sourceTemplate.value) || "The source revision is not runnable in its current state.";
  }
  return "Current source state has not been checked.";
});

// The runtime has gone quiet: everything derived from the newest report is
// last-known rather than current, and the whole page has to say so rather than
// keep rendering stale values as if they were live.
const reportUnproven = computed(() => isOutboxUnproven(detail.value?.outbox_health));

// The compact rail above the tabs. Built from the RAW per-device stream states,
// not from the session-level `health` rollup — that rollup is lossy by design
// (see session-flow-status.js) and cannot say which stream or why.
const streamRows = computed(() =>
  deriveStreamRows({
    devices: detail.value?.latest_report?.devices ?? [],
    sinks: detail.value?.sinks ?? [],
    configuredFlows: detail.value?.session?.device_flows ?? [],
    unproven: reportUnproven.value,
  }),
);

const sessionDeviceFlows = computed(() => {
  const reportDevices = detail.value?.latest_report?.devices ?? [];
  const configuredFlows = detail.value?.session?.device_flows ?? [];
  return reportDevices.map((device, index) => {
    const configured = configuredFlows[index] ?? {};
    const sinks = (detail.value?.sinks ?? [])
      .filter((sink) => sink.source_id === device.device_id)
      .map((sink) => ({
        name: sink.sink_id,
        sink_id: sink.sink_id,
        path: sink.output?.canonical_path ?? sink.output?.base_path,
        // A null `health` means the newest report did not carry this sink, and
        // the runtime only reports sinks that have errored — so this is the
        // no-news case, not an unknown one. formatStatus() alone turned it into
        // "Unknown" and made every working sink look unaccounted for.
        health: sink.health ? formatStatus(sink.health) : "No errors",
        status: sink.status,
      }));
    return {
      id: device.device_id ?? `device-${index}`,
      device: device.device_id ?? "Unknown device",
      type: configured.device_type ?? configured.type ?? "Unknown type",
      hardwareId: configured.hardware_id ?? "Unknown hardware",
      health: formatStatus(device.stream_status),
      reason: device.reason,
      action: device.action,
      pendingRecovery: device.pending_recovery,
      rate: "Unavailable",
      lastData: formatCentralTimestamp(detail.value?.latest_report?.received_at, { fallback: "Unavailable" }),
      watchdog: formatStatus(detail.value?.watchdog_state),
      sinks,
    };
  });
});
// An incident means someone is waiting; a gap means data is missing. They are
// different questions, so they are different things on screen even though the
// backend ships them in one payload.
//
// Incidents also arrive on two surfaces (IncidentSchema.axis): the DATA PATH — a
// device that stopped producing, a sink that stopped accepting — sits beside the
// gaps it produces, and the CONTROL PLANE — processes, telemetry, failed
// commands — sits with operations, because those are things the machinery did
// rather than data you lost. Unknown/absent `axis` falls to the data path so an
// older backend degrades to showing a row rather than hiding it.
const OPEN_INCIDENT_STATUSES = new Set(["open", "acknowledged"]);

const detailIncidents = computed(() => detail.value?.incidents ?? []);
const detailGaps = computed(() => detail.value?.gaps ?? []);
const recovery = computed(() => detail.value?.recovery ?? null);
const recoveryPolicy = computed(() => view.value.policy ? formatStatus(view.value.policy) : "Unavailable");
// Already fetched on every poll and, until now, dropped on the floor.
const detailOperations = computed(() => detail.value?.operations ?? []);
const timelineEntries = computed(() => (
  activityRecords.value.length
    ? buildActivityTimeline(activityRecords.value)
    : buildSessionTimeline({
        events: activity.value.events,
        incidents: detailIncidents.value,
        gaps: detailGaps.value,
        operations: detailOperations.value,
      })
));
const recoveryOutputs = computed(() =>
  (detail.value?.sinks ?? [])
    .filter((sink) => sink.output?.component_count > 1)
    .map((sink) => ({ sinkId: sink.sink_id, ...sink.output })),
);
// Once clean-shutdown proof is missing, later retries commonly fail with
// RuntimeNotTracked because the ambiguous stop already tore down the host.
// Those retries must not hide the force-stop escape hatch while the session is
// still Active; the lifecycle removes the action after a successful stop.
const forceStopRequired = computed(() =>
  detailOperations.value.some((operation) => {
    const errorCode = String(operation?.error_code ?? "")
      .replace(/[^a-z0-9]/gi, "")
      .toLowerCase();
    return (
      String(operation?.command).toLowerCase() === "stop" &&
      String(operation?.state).toLowerCase() === "failed" &&
      errorCode === "stopproofmissing"
    );
  }),
);

/** Unresolved — `ack` is an annotation, not a resolution. */
function isOpenIncident(incident) {
  return OPEN_INCIDENT_STATUSES.has(incident.status);
}

/**
 * Waiting on a PERSON, not on the system. A crashed watchdog respawns itself and
 * an unreachable host is reconciled — those are worth showing and wrong to badge,
 * because there is no lever an operator can pull that the supervisor is not
 * already pulling. `needs_action` is served by the backend so the rule lives in
 * one place; an older backend that omits it degrades to badging everything.
 */
function isWaitingOnOperator(incident) {
  return isOpenIncident(incident) && incident.needs_action !== false;
}

const openIssues = computed(() => detailIncidents.value.filter(isOpenIncident));
// Badge inputs — a strict subset of the tables above, which still show
// everything unresolved so a self-healing condition stays visible while it heals.
const actionableIssues = computed(() => detailIncidents.value.filter(isWaitingOnOperator));

// Which record sections on the Incidents and Operations tabs start expanded.
//
// Both tabs pair a NEEDS-ACTION table with a HISTORY table, and history is the
// one that grows without bound — a long healthy run accumulates gaps and
// commands forever. Leading with history buries the two or three rows an
// operator actually came for, so the rule is: open what is waiting on someone,
// collapse what is merely recorded. When nothing is waiting, the history opens
// instead, because a tab of collapsed headers looks broken rather than calm.
// The all-empty case opens the lead section so its reassurance is the thing on
// screen ("Nothing is waiting on you") rather than a bare `0`.
//
// These are DEFAULTS, not locks: CollapsibleSection owns the open state after
// first render, so an operator's own toggle stands until the flag flips again.
const openSections = computed(() => {
  const incidents = openIssues.value.length > 0;
  const gaps = detailGaps.value.length > 0;
  return {
    incidents: incidents || !gaps,
    gaps: gaps && !incidents,
  };
});

const detailUnavailable = computed(() => detailState.value === "unavailable");

// The rat (in Session Summary) and the rail (in Stream Health) are now in
// different cards but must never disagree, so both resolve from ONE set of
// inputs: this object is bound onto SessionFlowBar and fed to deriveFlowStatus
// for the rat. Restating the argument list at either call site is what would let
// a running rat end up beside a red rail.
const flowInputs = computed(() => {
  const resolvedFlows = detail.value?.session?.device_flows ?? [];
  return {
    lifecycle: lifecycle.value,
    health: view.value.health,
    phase: view.value.phase,
    activityState: activity.value.state,
    detailAvailable: !detailUnavailable.value,
    streams: streamRows.value,
    configuredFlows: resolvedFlows.length ? resolvedFlows : sourceInformationFlows.value,
    outboxHealth: detail.value?.outbox_health ?? null,
  };
});

const ratState = computed(() =>
  deriveRatState(deriveFlowStatus(flowInputs.value), streamRows.value),
);

const ratCaption = computed(() => {
  const captions = {
    running: "Session streaming",
    recovering: "Session recovering",
    suspect: "Stream needs attention",
    paused: "Session idle",
    stopped: "Session stalled",
  };
  return captions[ratState.value] ?? "Session status unavailable";
});

const collection = computed(() => {
  if (isRunningLifecycle(lifecycle.value)) return "Running";
  if (lifecycle.value === "Completed") return "Closed";
  return "Idle";
});

function formatStatus(value) {
  if (!value) return "Unknown";
  return String(value)
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

// Why an incident reached an operator, in their words rather than the wire's.
// The backend records the cause on the incident at the moment it escalated
// (app/services/escalation.py), because a later report no longer shows the
// condition that triggered it.
const ESCALATION_CAUSES = {
  watchdog_auto_recovery_exhausted: "Automatic recovery gave up",
  recommend_policy_awaits_operator: "Recommend policy — waiting for you",
  port_absent_beyond_threshold: "Port absent too long",
  sink_did_not_recover_with_source: "Did not return with its source",
};

function escalationCause(incident) {
  if (incident.details?.message) {
    const type = incident.details?.exception_type;
    return type ? `${type}: ${incident.details.message}` : incident.details.message;
  }
  const cause = incident.details?.escalation_cause;
  if (!cause) return "—";
  return ESCALATION_CAUSES[cause] ?? formatStatus(cause);
}

/** A gap's missing-data window, or an honest statement that it is unproven. */
function gapWindow(gap) {
  // gap_start/gap_end are declared on the schema but nothing populates them yet:
  // the report wire carries no segment offsets, so the plane cannot prove where
  // the pre-gap segment ended (see app/services/gaps.py). Saying so is better
  // than rendering two empty cells that look like a rendering bug.
  if (!gap.gap_start && !gap.gap_end) return "Boundaries not reported";
  return `${gap.gap_start ?? "?"} → ${gap.gap_end ?? "?"}`;
}

function formatTimestamp(value) {
  return formatCentralTimestamp(value, { fallback: value ? String(value) : "—" });
}

function normalizeTemplatePath(value) {
  return String(value ?? "").replaceAll("\\", "/").replace(/^\.\//, "").toLowerCase();
}

function formatTemplateStatLabel(key) {
  return String(key)
    .replaceAll("_", " ")
    .split(" ")
    .map((word) => ({ id: "ID", ss: "SS" })[word.toLowerCase()] ?? `${word.charAt(0).toUpperCase()}${word.slice(1)}`)
    .join(" ");
}

function formatTemplateStatValue(value) {
  if (Array.isArray(value)) {
    const groups = [];
    for (const item of value) {
      const display = formatTemplateStatValue(item);
      const last = groups.at(-1);
      if (last?.value === display) last.count += 1;
      else groups.push({ value: display, count: 1 });
    }
    return groups.map((group) => `${group.value}${group.count > 1 ? ` ×${group.count}` : ""}`).join(", ");
  }
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

// While spectating, /status is re-read on a slow timer AND opportunistically
// whenever the event stream delivers something new. The timer alone would lag a
// state change by up to its interval; the event trigger alone would go blind if
// the SSE connection dropped. Together the bar stays honest under both failures.
const DETAIL_POLL_MS = 5000;
const EVENT_REFRESH_DEBOUNCE_MS = 100;

async function resolveSourceTemplate({ force = false } = {}) {
  const templateId = sourceTemplateId.value;
  if (!templateId) {
    sourceTemplate.value = null;
    sourceTemplateState.value = "idle";
    sourceTemplateError.value = "";
    resolvedSourceTemplateId = null;
    return;
  }
  if (!force && resolvedSourceTemplateId === templateId && sourceTemplateState.value !== "idle") return;

  const request = ++sourceTemplateRequest;
  resolvedSourceTemplateId = templateId;
  sourceTemplate.value = null;
  sourceTemplateState.value = "loading";
  sourceTemplateError.value = "";
  try {
    const current = await loadSessionTemplate(templateId);
    if (request !== sourceTemplateRequest) return;
    sourceTemplate.value = current;
    sourceTemplateState.value = "live";
  } catch (error) {
    if (request !== sourceTemplateRequest) return;
    sourceTemplateState.value = "unavailable";
    sourceTemplateError.value =
      error instanceof Error
        ? error.message
        : "The source template could not be resolved. Restore or reconcile it before starting another run.";
  }
}

async function resolveSourceDeviceTemplates({ force = false } = {}) {
  if (!sourceInformationFlows.value.length) return;
  if (!force && ["loading", "live"].includes(sourceDeviceTemplatesState.value)) return;
  sourceDeviceTemplatesState.value = "loading";
  sourceDeviceTemplatesError.value = "";
  try {
    sourceDeviceTemplates.value = await loadDeviceTemplates();
    sourceDeviceTemplatesState.value = "live";
  } catch (error) {
    sourceDeviceTemplatesState.value = "unavailable";
    sourceDeviceTemplatesError.value = error instanceof Error
      ? error.message
      : "Device-template stats are unavailable.";
  }
}

function formatRecoveryEvidence(value) {
  if (value === null || value === undefined) return "Unavailable";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return "Unavailable";
  }
}

async function startAnotherRun() {
  // Revalidate at the click boundary as well as on page load. Unit 14 repeats
  // this check before create, but a stale button must not navigate there after
  // the source changes state in another process.
  await resolveSourceTemplate({ force: true });
  if (sourceTemplateRunnable.value) {
    emit("start-another-run", sourceTemplate.value.templateId);
  }
}

/** `silent` keeps a background refresh from flashing the page back to loading. */
async function refreshDetail({ silent = false } = {}) {
  if (!silent) detailState.value = "loading";
  try {
    detail.value = await loadSessionDetail(props.sessionId);
    detailState.value = "live";
    detailError.value = "";
    // The server has now spoken; drop any optimistic post-command lifecycle.
    pendingLifecycle.value = null;
    await resolveSourceTemplate();
    await resolveSourceDeviceTemplates();
  } catch (error) {
    // A failed *background* refresh keeps the last good snapshot on screen —
    // blanking a live view because one poll missed is worse than mild staleness.
    if (!silent) detail.value = null;
    detailState.value = "unavailable";
    detailError.value = error instanceof Error ? error.message : "Session detail is unavailable.";
  }
}

async function refreshActivity() {
  try {
    const page = await loadSessionActivity(props.sessionId);
    activityRecords.value = page.items ?? [];
    activityRecordsState.value = "live";
    activityRecordsError.value = "";
  } catch (error) {
    activityRecordsState.value = "unavailable";
    activityRecordsError.value = error instanceof Error ? error.message : "Activity is unavailable.";
  }
}

function scheduleActivityRefresh() {
  if (activityRefreshTimer !== null) clearTimeout(activityRefreshTimer);
  activityRefreshTimer = setTimeout(() => {
    activityRefreshTimer = null;
    refreshActivity();
  }, EVENT_REFRESH_DEBOUNCE_MS);
}

function scheduleDetailRefresh() {
  if (detailRefreshTimer !== null) clearTimeout(detailRefreshTimer);
  detailRefreshTimer = setTimeout(() => {
    detailRefreshTimer = null;
    refreshDetail({ silent: true });
  }, EVENT_REFRESH_DEBOUNCE_MS);
}

function onActivitySnapshot(snapshot) {
  const previousEventId = activity.value.events.at(-1)?.id;
  const latestEventId = snapshot.events.at(-1)?.id;
  const latestEvent = latestEventId != null && latestEventId !== previousEventId
    ? snapshot.events.at(-1)
    : null;
  activity.value = snapshot;
  if (!latestEvent) return;

  // Replayed runtime reports update status only. Activity is reloaded from the
  // durable ledger after its named notification, which is committed after the
  // source fact and therefore cannot race ahead of the gap/issue write.
  if (isSessionActivityEvent(latestEvent)) scheduleActivityRefresh();
  // A trailing debounce collapses the initial SSE replay into one status read
  // and lets a following gap/activity notification win the race to the timer.
  scheduleDetailRefresh();
}

async function refreshNotes() {
  notesState.value = "loading";
  notesError.value = "";
  try {
    const page = await loadSessionNotes(props.sessionId);
    notes.value = page.items ?? [];
    notesState.value = "live";
  } catch (error) {
    notesState.value = "unavailable";
    notesError.value = error instanceof Error ? error.message : "Notes are unavailable.";
  }
}

function openNewNote() {
  noteEditor.value = { noteId: null };
  noteBody.value = "";
  noteShowTimestamp.value = false;
  noteSaveError.value = "";
}

function openEditNote(note) {
  noteEditor.value = { noteId: note.id };
  noteBody.value = note.body;
  noteShowTimestamp.value = Boolean(note.show_timestamp);
  noteSaveError.value = "";
}

function closeNoteEditor() {
  if (!noteBusy.value) noteEditor.value = null;
}

const noteCanSave = computed(() => {
  const length = noteBody.value.trim().length;
  return length > 0 && length <= 4000 && !noteBusy.value;
});

async function saveNote() {
  if (!noteCanSave.value || !noteEditor.value) return;
  noteBusy.value = true;
  noteSaveError.value = "";
  const payload = {
    body: noteBody.value.trim(),
    showTimestamp: noteShowTimestamp.value,
  };
  try {
    if (noteEditor.value.noteId === null) {
      const created = await createSessionNote(props.sessionId, payload);
      notes.value = [created, ...notes.value];
    } else {
      const updated = await updateSessionNote(props.sessionId, noteEditor.value.noteId, payload);
      notes.value = notes.value.map((note) => note.id === updated.id ? updated : note);
    }
    notesState.value = "live";
    noteEditor.value = null;
  } catch (error) {
    noteSaveError.value = error instanceof Error ? error.message : "The note could not be saved.";
  } finally {
    noteBusy.value = false;
  }
}

onMounted(() => {
  refreshDetail();
  refreshActivity();
  refreshNotes();
  eventStream = createSessionEventStream({
    sessionId: props.sessionId,
    onChange: onActivitySnapshot,
  });
  eventStream.start();
  // Completed sessions only change through this page's
  // own commands, which refetch directly — no need to poll those.
  pollTimer = setInterval(() => {
    if (isRunningLifecycle(lifecycle.value) || ["Scheduled", "Unknown"].includes(lifecycle.value)) {
      refreshDetail({ silent: true });
    }
  }, DETAIL_POLL_MS);
});
onUnmounted(() => {
  eventStream?.stop();
  if (pollTimer) clearInterval(pollTimer);
  if (activityRefreshTimer !== null) clearTimeout(activityRefreshTimer);
  if (detailRefreshTimer !== null) clearTimeout(detailRefreshTimer);
});

function applyCommandResult(result) {
  const labels = { preparing: "Preparing", scheduled: "Scheduled", starting: "Starting", active: "Active", ending: "Ending", stopped: "Completed", completed: "Completed", cancelled: "Cancelled" };
  if (result?.status && labels[result.status]) pendingLifecycle.value = labels[result.status];
  emit("state-changed", result);
}

function problemMessage(error, fallback) {
  return error?.problem?.detail ?? (error instanceof Error ? error.message : fallback);
}

function dismissCommandError() {
  commandError.value = "";
  commandProblem.value = null;
}

async function runLifecycleCommand(command) {
  if (commandBusy.value) return;
  commandBusy.value = true;
  dialog.value = null;
  commandError.value = "";
  commandProblem.value = null;
  try {
    const result = await command();
    applyCommandResult(result);
    await refreshDetail();
    await refreshActivity();
  } catch (error) {
    commandProblem.value = error?.problem ?? null;
    commandError.value = problemMessage(error, "The lifecycle command failed.");
    // Pull the persisted operation outcome immediately so a failed normal Stop
    // can turn the action into Force Stop without waiting for the next poll.
    await refreshDetail({ silent: true });
    await refreshActivity();
  } finally {
    commandBusy.value = false;
  }
}

function openStopDialog() {
  dismissCommandError();
  dialog.value = forceStopRequired.value ? "force-stop" : "stop";
}

function confirmStop() {
  return runLifecycleCommand(() => stopSession(props.sessionId));
}

function openForceStopDialog() {
  dismissCommandError();
  dialog.value = "force-stop";
}

function confirmForceStop() {
  return runLifecycleCommand(() => stopSession(props.sessionId, { force: true }));
}

function sinkIsPlot(sink) {
  const type = sink.type ?? sink.sink_type ?? sink.sinkClass ?? sink.sink_class;
  return (
    type === "plot" ||
    /plot/i.test(String(sink.name ?? "")) ||
    /plot/i.test(String(sink.path ?? ""))
  );
}

function artifactLabel(state) {
  return {
    merge_pending: "Waiting to finalize",
    merging: "Building verified output",
    merged: "Verified and ready",
    merge_failed: "Finalization will retry",
    merge_blocked: "Finalization needs attention",
    not_required: "No merge required",
  }[state] ?? "Finalization state unavailable";
}

function formatCount(value) {
  return Number(value ?? 0).toLocaleString();
}

function normalizeSessionId(id) {
  if (typeof id === "number") return id;
  const digits = String(id ?? "").replace(/\D/g, "");
  return digits ? Number(digits) : id;
}

/** Plot integration remains deferred until its backend contract is available. */
const plotTargets = computed(() => {
  return [];
});

const visibleTabs = computed(() => [
  { id: "overview", label: "Overview" },
  { id: "streams", label: "Streams" },
  ...(plotTargets.value.length ? [{ id: "plot", label: "Live Plot" }] : []),
  { id: "recovery", label: "Recovery" },
  { id: "incidents", label: "Issues & Data Gaps" },
  { id: "activity", label: "Activity" },
  { id: "diagnostics", label: "Diagnostic Logs" },
  { id: "configuration", label: "Configuration" },
]);

// Badges on the tab strip, so "which tab should I open" is answerable without
// opening one. Deliberately counts only what needs ATTENTION rather than totals:
// a "Streams 3" badge on a healthy session is noise that trains operators to
// ignore the badge.
const tabCounts = computed(() => {
  const counts = {};
  const troubled = streamRows.value.filter((row) => row.tone !== "good").length;
  if (troubled) counts.streams = troubled;
  // Gaps are deliberately NOT counted. A gap is a permanent record, so counting
  // them makes the badge climb forever on a long, healthy run — and resolved
  // incidents are excluded for the same reason. The badge answers "is anything
  // waiting on me right now", which is the only question that earns a red dot.
  if (actionableIssues.value.length) counts.incidents = actionableIssues.value.length;
  if (detail.value?.recovery) counts.recovery = 1;
  return counts;
});

const tabTones = computed(() => ({
  streams: streamRows.value.some((row) => row.tone === "bad") ? "bad" : "warn",
  incidents: actionableIssues.value.length ? "bad" : "warn",
  recovery: "warn",
}));

// `sinkSummary()` lived here to caption the Overview "Stream Health" tiles.
// Those tiles are gone (the flow rail replaced them) and the rail carries the
// same fact per row as `sinkNote`, from summarizeSinks() — so the helper had no
// remaining caller. The Streams tab still shows per-sink health badges.
</script>

<template>
  <div class="page page--detail">
    <button class="back-link" type="button" @click="$emit('back')"><ArrowLeft :size="16" /> Sessions</button>
    <header class="detail-header">
      <div>
        <div class="title-row">
          <h1>{{ view.name }}</h1>
          <StatusBadge :value="lifecycle" />
          <StatusBadge :value="view.health" />
        </div>
        <p v-if="view.experiment"><FlaskConical :size="16" /> {{ view.experiment }}</p>
        <!-- `view.duration` used to be rendered here as `?? "Not started"`.
             normalizeSession() never sets a `duration` key and no endpoint
             supplies one, so the fallback was unconditional: every session, in
             every lifecycle, displayed "Not started" — including running ones.
             Elapsed run time needs a real `started_at` on the session payload
             (today it only exists on RuntimeOwnership), so the slot is dropped
             rather than kept as a placeholder that lies. Report age lives in the
             flow bar, on a clock that actually ticks. -->
        <div class="detail-metadata">
          <span>{{ view.streamCount ?? view.deviceCount }} streams / {{ view.sinkCount }} sinks</span>
          <StatusBadge compact label="Monitor" :value="view.watchdog" />
        </div>
      </div>
      <div class="detail-actions">
        <BaseButton
          v-if="sourceTemplateRunnable"
          variant="primary"
          title="Start another run from this completed session's source template"
          @click="startAnotherRun"
        >
          <Play :size="16" /> Run source template
        </BaseButton>
        <BaseButton
          v-if="isRunningLifecycle(lifecycle)"
          variant="danger"
          :disabled="commandBusy"
          :title="forceStopRequired ? 'The previous Stop could not prove a clean shutdown' : 'Stop this session cleanly'"
          @click="openStopDialog"
        >
          <StopCircle :size="16" /> {{ forceStopRequired ? "Force Stop" : "Stop" }}
        </BaseButton>
      </div>
    </header>

    <BaseCard class="detail-content">
      <TabBar
        class="detail-tabs"
        :tabs="visibleTabs"
        :active="activeTab"
        :counts="tabCounts"
        :tones="tabTones"
        @change="activeTab = $event"
      />

      <div v-if="activeTab === 'overview'" class="detail-grid">
        <BaseCard class="detail-panel">
          <h3>Session Summary</h3>
          <div class="session-summary__overview">
            <dl class="detail-list session-summary__details">
              <div><dt>Ownership</dt><dd>{{ view.isOwner ? "Owner session" : "Monitoring only" }}</dd></div>
              <div><dt>Experiment</dt><dd>{{ view.experiment ?? "Ungrouped" }}</dd></div>
              <div v-if="view.scheduledTime"><dt>Scheduled start</dt><dd>{{ formatTimestamp(view.scheduledTime) }}</dd></div>
              <div v-if="view.fallbackPolicy"><dt>Device policy</dt><dd>{{ formatStatus(view.fallbackPolicy) }}</dd></div>
              <div v-if="view.cancellation"><dt>Cancellation</dt><dd>{{ view.cancellation.detail ?? view.cancellation.code }}</dd></div>
            </dl>
            <div class="session-rat">
              <RatRunIndicator :state="ratState" size="lg" />
              <p :class="`session-rat__caption session-rat__caption--${ratState}`">{{ ratCaption }}</p>
            </div>
          </div>
          <SessionNotesList
            :notes="notes"
            :state="notesState"
            :error="notesError"
            @add="openNewNote"
            @edit="openEditNote"
          />
        </BaseCard>
        <!-- Stream Health IS the flow bar. These were two renderings of the same
             per-device facts sitting on one screen — the rail carried label,
             stream status and sink note, the tiles carried label, hardware id,
             stream status and sink summary. The rail absorbed the hardware id
             (see flow-rail__hardware) and the tiles are gone.

             Half width, beside Session Summary. The rail relayouts itself below
             ~26rem rather than squeezing its three columns — see the container
             query in SessionFlowBar. -->
        <BaseCard class="detail-panel">
          <h3>Stream Health</h3>
          <SessionFlowBar
            v-bind="flowInputs"
            :last-report-at="detail?.latest_report?.received_at ?? null"
          />
          <div class="stream-health-activity">
            <SessionTimeline
              variant="preview"
              :entries="timelineEntries"
              :state="activity.state"
              :error="activity.error"
              @view-all="activeTab = 'activity'"
            />
          </div>
        </BaseCard>
        <BaseCard
          v-if="hasSourceProvenance"
          class="detail-panel detail-panel--wide source-template-card"
        >
          <header class="source-template-heading">
            <div>
              <h3>Source template</h3>
              <p>Immutable provenance captured when this run was created.</p>
            </div>
            <StatusBadge v-if="sourceTemplateState === 'live'" :value="sourceTemplate.state" />
          </header>
          <p :class="{ 'form-notice': sourceTemplateState === 'unavailable' || (sourceTemplateState === 'live' && !canRunTemplate(sourceTemplate)) }">
            {{ sourceTemplateGuidance }}
          </p>
          <dl class="source-template-summary">
            <div><dt>Recovery policy</dt><dd>{{ formatStatus(sourceInformationContent?.policy) }}</dd></div>
            <div><dt>Streams</dt><dd>{{ sourceInformationFlows.length }}</dd></div>
            <div><dt>Sinks</dt><dd>{{ sourceInformationSinkCount }}</dd></div>
          </dl>
          <dl class="detail-list source-template-identity">
            <div><dt>Stored name</dt><dd>{{ detail?.session?.source_template_name ?? "Unavailable" }}</dd></div>
            <div><dt>Stored reference</dt><dd><code>{{ detail?.session?.source_template_ref ?? "Unavailable" }}</code></dd></div>
            <div><dt>Template revision ID</dt><dd><code>{{ sourceTemplateId ?? "Unavailable" }}</code></dd></div>
            <div><dt>Accepted hash</dt><dd><code>{{ detail?.session?.source_template_hash ?? "Unavailable" }}</code></dd></div>
          </dl>

          <section v-if="sourceFlowDetails.length" class="source-flow-list" aria-label="Source template stream configuration">
            <article v-for="(flow, flowIndex) in sourceFlowDetails" :key="flow.key" class="source-flow">
              <header class="source-flow__heading">
                <div>
                  <span>Stream {{ flowIndex + 1 }}</span>
                  <h4>{{ flow.title }}</h4>
                  <code>{{ flow.path || "Device template unavailable" }}</code>
                </div>
                <span v-if="flow.revisionMatches" class="source-flow__revision source-flow__revision--matched">
                  Accepted device revision
                </span>
                <span v-else-if="flow.revisionDiffers" class="source-flow__revision source-flow__revision--changed">
                  Current TOML differs from this run
                </span>
              </header>

              <p v-if="flow.revisionDiffers" class="source-flow__notice">
                The values below come from the current device-template TOML. The run retained a different accepted hash.
              </p>
              <dl v-if="flow.stats.length" class="source-flow__stats">
                <div v-for="stat in flow.stats" :key="stat.label">
                  <dt>{{ stat.label }}</dt>
                  <dd>{{ stat.value }}</dd>
                </div>
              </dl>
              <p v-else class="source-flow__notice">{{ flow.statsUnavailable }}</p>

              <div class="source-flow__sinks">
                <h5>Sinks</h5>
                <p v-if="!flow.sinks.length">No sinks configured.</p>
                <ul v-else>
                  <li v-for="sink in flow.sinks" :key="sink.key">
                    <strong>{{ sink.name }}</strong>
                    <span>{{ formatStatus(sink.type) }}</span>
                    <code v-if="sink.location">{{ sink.location }}</code>
                    <span v-for="[key, value] in sink.parameters" :key="key">
                      {{ formatTemplateStatLabel(key) }}: {{ formatTemplateStatValue(value) }}
                    </span>
                  </li>
                </ul>
              </div>
              <details v-if="flow.expectedHash" class="source-flow__revision-details">
                <summary>Device-template revision</summary>
                <code>{{ flow.expectedHash }}</code>
              </details>
            </article>
          </section>
          <p v-else class="form-notice">No stream configuration was stored with this source template.</p>

          <details v-if="sourceTemplateSnapshot" class="source-snapshot">
            <summary>Frozen source snapshot</summary>
            <p>Canonical hash version <code>{{ sourceTemplateSnapshot.canonical_hash_version }}</code></p>
            <pre>{{ sourceSnapshotJson }}</pre>
          </details>
          <p v-else class="form-notice">No frozen source snapshot was stored for this legacy run.</p>
          <BaseButton
            v-if="sourceTemplateState === 'unavailable' && sourceTemplateId"
            variant="secondary"
            @click="resolveSourceTemplate({ force: true })"
          >
            Retry source lookup
          </BaseButton>
          <BaseButton
            v-if="sourceDeviceTemplatesState === 'unavailable'"
            variant="secondary"
            @click="resolveSourceDeviceTemplates({ force: true })"
          >
            Retry device-template stats
          </BaseButton>
        </BaseCard>
        <!-- Only rendered when there IS a recovery. Its entire content was
             otherwise "No active recovery context is reported." — a permanent
             card whose job was to say nothing, while the Recovery tab already
             shows the same thing with phase, attempt and hardware access. Wide,
             because it is now the only thing on its row. -->
        <BaseCard v-if="detailUnavailable || detail?.recovery" class="detail-panel detail-panel--wide">
          <h3>Current Recovery</h3>
          <p v-if="detailUnavailable">Recovery status is unavailable.</p>
          <p v-else>{{ detail.recovery.operator_message }}</p>
          <BaseButton v-if="detail?.recovery" @click="dialog = 'approve'"><Shield :size="16" /> Review Action</BaseButton>
        </BaseCard>
      </div>

      <div v-else-if="activeTab === 'streams'" class="flow-list">
        <BaseCard v-for="flow in sessionDeviceFlows" :key="flow.id" class="flow-card">
          <header><div><h3>{{ flow.device }} <small>{{ flow.type }}</small></h3><code>{{ flow.hardwareId }}</code></div><StatusBadge :value="flow.health" /></header>
          <dl class="flow-metrics">
            <div><dt>Data rate</dt><dd>{{ flow.rate }}</dd></div>
            <div><dt>Last data</dt><dd>{{ flow.lastData }}</dd></div>
            <div><dt>Session Monitor</dt><dd>{{ flow.watchdog }}</dd></div>
            <div><dt>Sink count</dt><dd>{{ flow.sinks.length }}</dd></div>
          </dl>
          <div v-if="flow.reason" class="form-notice" role="alert">
            <strong>Failure:</strong> {{ flow.reason }}
          </div>
          <div class="sink-list">
            <div v-for="sink in flow.sinks" :key="sink.name">
              <strong>{{ sink.name }}</strong>
              <code>{{ sink.path ?? sink.sink_id ?? sink.type ?? "—" }}</code>
              <StatusBadge compact :value="sink.health" />
              <BaseButton
                v-if="sinkIsPlot(sink)"
                variant="secondary"
                size="small"
                @click="activeTab = 'plot'"
              >
                Open live plot
              </BaseButton>
            </div>
          </div>
          <div class="card-actions">
            <BaseButton variant="secondary"><Shield :size="16" /> Recover Stream</BaseButton>
            <BaseButton variant="secondary"><ExternalLink :size="16" /> Open Device</BaseButton>
            <BaseButton variant="secondary"><ExternalLink :size="16" /> Open Output</BaseButton>
          </div>
        </BaseCard>
      </div>

      <div v-else-if="activeTab === 'plot'" class="flow-list">
        <BaseCard class="detail-panel">
          <h3>Live Plot</h3>
          <p>Live Plot integration is deferred until its backend transport contract is available.</p>
        </BaseCard>
      </div>

      <div v-else-if="activeTab === 'recovery'" class="recovery-layout">
        <BaseCard class="detail-panel"><h3>Assigned Policy</h3><dl class="detail-list"><div><dt>Policy</dt><dd>{{ recoveryPolicy }}</dd></div><div><dt>Verification</dt><dd>Device, sink, data rate</dd></div></dl></BaseCard>
        <BaseCard class="detail-panel">
          <h3>Recovery Activity</h3>
          <div v-if="detailUnavailable" class="detail-alert">Recovery data unavailable.</div>
          <div v-else-if="detail?.recovery" class="phase-list"><span class="current">{{ detail.recovery.phase }}</span><span>Attempt {{ detail.recovery.attempt }}</span><span>{{ detail.recovery.hardware_access }}</span></div>
          <div v-else class="phase-list"><span>No recovery reported</span></div>
          <div class="card-actions">
            <BaseButton @click="dialog = 'approve'"><Play :size="16" /> Approve Recovery</BaseButton>
            <BaseButton variant="secondary">Retry Recovery</BaseButton>
            <BaseButton variant="secondary">Mark Resolved</BaseButton>
          </div>
        </BaseCard>
        <BaseCard class="detail-panel detail-panel--wide recovery-story" aria-live="polite">
          <header class="recovery-story__heading">
            <div>
              <h3>Verified Recovery Story</h3>
              <p>Canonical output and retained source components for this run.</p>
            </div>
            <StatusBadge
              v-if="recoveryOutputs.length === 1"
              :value="artifactLabel(recoveryOutputs[0].artifact_state)"
            />
          </header>
          <p v-if="detailUnavailable" class="detail-alert">Output verification is unavailable.</p>
          <p v-else-if="!recoveryOutputs.length" class="records-empty">
            This run has no segmented file output requiring a merge.
          </p>
          <template v-else>
            <article
              v-for="output in recoveryOutputs"
              :key="output.logical_sink_id"
              class="recovery-output"
            >
              <div class="recovery-output__summary">
                <div>
                  <strong>{{ output.sinkId }}</strong>
                  <span>{{ artifactLabel(output.artifact_state) }}</span>
                </div>
                <dl class="recovery-output__metrics">
                  <div><dt>Recoveries</dt><dd>{{ formatCount(output.recovery_count) }}</dd></div>
                  <div><dt>Components</dt><dd>{{ formatCount(output.component_count) }}</dd></div>
                  <div><dt>Captured samples</dt><dd>{{ formatCount(output.captured_samples) }}</dd></div>
                  <div><dt>Known sample loss</dt><dd>{{ formatCount(output.sample_loss) }}</dd></div>
                </dl>
              </div>
              <div v-if="output.canonical_path" class="canonical-output">
                <span>Canonical {{ output.verified ? "verified" : "recorded" }} file</span>
                <code>{{ output.canonical_path }}</code>
                <small v-if="output.sink_type === 'pvfs' && output.verified">
                  Original timestamps and real recovery gaps are preserved in the PVFS timeline.
                </small>
              </div>
              <div v-else class="detail-alert">
                No canonical merged file has been published. The retained components remain available.
              </div>
              <details class="recovery-components">
                <summary>Retained recovery components ({{ output.component_count }})</summary>
                <ol>
                  <li v-for="component in output.components" :key="component.output_id">
                    <code>{{ component.path }}</code>
                    <span>
                      Segment {{ component.segment_index + 1 }} ·
                      {{ formatCount(component.captured_samples) }} samples ·
                      {{ component.termination_reason ?? component.acquisition_state }}
                    </span>
                  </li>
                </ol>
              </details>
            </article>
          </template>
        </BaseCard>
      </div>

      <!-- Two surfaces, not one merged list. The incidents table is what is
           waiting on a person right now; the gap log is a permanent record of
           missing data that nobody has to act on. Merging them meant a gap
           carrying a linked incident_id rendered under the INCIDENT's id — so
           its own gap_id was never shown anywhere and both rows shared a Vue
           key. Each table now keys on its own identifier. -->
      <div v-else-if="activeTab === 'incidents'" class="records-layout">
        <BaseCard v-if="detailUnavailable" class="detail-panel">
          <p class="records-empty">Issues and data gaps are unavailable.</p>
        </BaseCard>
        <template v-else>
          <BaseCard class="detail-panel detail-panel--records">
            <CollapsibleSection
              title="Open issues"
              hint="Unresolved data-path and system problems"
              :count="openIssues.length"
              :tone="actionableIssues.length ? 'bad' : 'neutral'"
              :default-open="openSections.incidents"
            >
              <p v-if="!openIssues.length" class="records-empty">
                Nothing is waiting on you. Streams recovering on their own are not listed here —
                they appear in the gap log once the episode closes.
              </p>
              <div v-else class="table-wrap">
                <table class="data-table records-table">
                  <thead>
                    <tr><th>Issue</th><th>Device</th><th>Sink</th><th>Reason</th><th>Why now</th><th>State</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="incident in openIssues" :key="incident.incident_id">
                      <td><code>{{ incident.incident_id }}</code></td>
                      <td><code>{{ incident.device_id ?? "—" }}</code></td>
                      <td><code>{{ incident.sink_id ?? "—" }}</code></td>
                      <td>{{ incident.reason }}</td>
                      <td>{{ escalationCause(incident) }}</td>
                      <td><StatusBadge compact :value="formatStatus(incident.status)" /></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </CollapsibleSection>
          </BaseCard>

          <!-- Neutral tone on purpose: the gap log is a permanent record, so its
               count is a fact about the run's length, not a queue of problems. -->
          <BaseCard class="detail-panel detail-panel--records">
            <CollapsibleSection
              title="Data gaps"
              hint="Permanent record of missing data — nothing to action"
              :count="detailGaps.length"
              :default-open="openSections.gaps"
            >
              <p v-if="!detailGaps.length" class="records-empty">
                No recovery gaps have been recorded for this session.
              </p>
              <div v-else class="table-wrap">
                <table class="data-table records-table">
                  <thead>
                    <tr><th>Gap</th><th>Device</th><th>Sink</th><th>Reason</th><th>Window</th><th>Confidence</th><th>Recorded</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="gap in detailGaps" :key="gap.gap_id">
                      <td><code>{{ gap.gap_id }}</code></td>
                      <td><code>{{ gap.device_id ?? "—" }}</code></td>
                      <td><code>{{ gap.sink_id ?? "—" }}</code></td>
                      <td>{{ gap.reason }}</td>
                      <td>{{ displayGapWindow(gap) }}</td>
                      <td>{{ formatStatus(gap.confidence) }}</td>
                      <td>{{ formatTimestamp(gap.created_at) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </CollapsibleSection>
          </BaseCard>
        </template>
      </div>

      <div v-else-if="activeTab === 'activity'">
        <SessionTimeline
          :entries="timelineEntries"
          :state="activityRecordsState === 'unavailable' ? 'unavailable' : activity.state"
          :error="activityRecordsError || activity.error"
        />
      </div>

      <div v-else-if="activeTab === 'diagnostics'">
        <SessionDiagnosticLog :session-id="props.sessionId" />
      </div>

      <div v-else-if="activeTab === 'configuration'" class="configuration-grid">
        <BaseCard class="detail-panel"><h3>Metadata</h3><dl class="detail-list"><div><dt>Name</dt><dd>{{ view.name }}</dd></div><div><dt>Experiment</dt><dd>{{ view.experiment ?? "None" }}</dd></div><div><dt>Schedule</dt><dd>{{ view.scheduledTime ? "One-time" : "Manual" }}</dd></div><div><dt>Recovery Policy</dt><dd>{{ recoveryPolicy }}</dd></div></dl></BaseCard>
        <BaseCard class="detail-panel"><h3>Runtime Lock</h3><p>Stream and sink configuration is immutable run history.</p></BaseCard>
        <BaseCard class="detail-panel">
          <h3>Output Locations</h3>
          <p>Output locations are frozen as run history.</p>
        </BaseCard>
      </div>
    </BaseCard>

    <GuardedDialog v-if="dialog === 'stop'" title="Stop Session" description="This concludes the current dataflow and marks the run Completed. This run cannot be restarted; another run must come from its source template." confirm-label="Stop Session" danger @close="dialog = null" @confirm="confirmStop">
      <div class="dialog-notice"><strong>Streams affected</strong><code v-for="flow in sessionDeviceFlows" :key="flow.id">{{ flow.device }}</code></div>
    </GuardedDialog>
    <GuardedDialog
      v-if="dialog === 'force-stop'"
      title="Force stop this session?"
      description="A clean shutdown could not be proven. Force stopping ends the session and releases its device claims, but its final output may be incomplete."
      confirm-label="Force Stop"
      danger
      @close="dialog = null"
      @confirm="confirmForceStop"
    >
      <div class="dialog-notice">
        <strong>Use only after the normal stop failed</strong>
        <span>The session cannot be restarted; start another run from its source template if needed.</span>
      </div>
    </GuardedDialog>
    <GuardedDialog v-if="dialog === 'approve'" title="Approve Recovery Action" :description="recovery?.operator_message ?? 'Recovery details are unavailable.'" :confirm-label="recovery ? 'Approve Recovery' : 'Close'" @close="dialog = null" @confirm="dialog = null">
      <dl class="detail-list"><div><dt>Policy</dt><dd>{{ recoveryPolicy }}</dd></div><div><dt>Reason</dt><dd>{{ recovery?.reason ? formatStatus(recovery.reason) : "Unavailable" }}</dd></div><div><dt>Phase</dt><dd>{{ recovery?.phase ? formatStatus(recovery.phase) : "Unavailable" }}</dd></div><div><dt>Attempt</dt><dd>{{ recovery?.attempt ?? "Unavailable" }}</dd></div><div><dt>Next retry</dt><dd>{{ recovery?.next_retry_at ? formatTimestamp(recovery.next_retry_at) : "Unavailable" }}</dd></div><div><dt>Hardware access</dt><dd>{{ recovery?.hardware_access ? formatStatus(recovery.hardware_access) : "Unavailable" }}</dd></div><div><dt>Evidence</dt><dd><code>{{ formatRecoveryEvidence(recovery?.evidence) }}</code></dd></div></dl>
    </GuardedDialog>
    <GuardedDialog
      v-if="noteEditor"
      :title="noteEditor.noteId === null ? 'Add note' : 'Edit note'"
      description="Notes are retained with this session. The timestamp is always stored; choose whether it is shown on the card."
      :confirm-label="noteBusy ? 'Saving…' : 'Save note'"
      :confirm-disabled="!noteCanSave"
      @close="closeNoteEditor"
      @confirm="saveNote"
    >
      <div class="dialog-form">
        <label class="field">
          <span>Note</span>
          <textarea v-model="noteBody" rows="6" maxlength="4000" placeholder="Add operator context…"></textarea>
        </label>
        <label class="note-timestamp-option">
          <input v-model="noteShowTimestamp" type="checkbox" />
          <span>Show timestamp with this note</span>
        </label>
        <p class="note-character-count">{{ noteBody.length }} / 4000</p>
        <p v-if="noteSaveError" class="form-notice" role="alert">{{ noteSaveError }}</p>
      </div>
    </GuardedDialog>
    <CommandErrorDialog
      v-if="commandError"
      :message="commandError"
      :action-label="forceStopRequired || commandProblem?.code === 'stop_proof_missing' ? 'Force Stop' : ''"
      @close="dismissCommandError"
      @action="openForceStopDialog"
    />
  </div>
</template>

<style scoped>
.detail-content {
  overflow: visible;
}

.detail-tabs {
  position: sticky;
  top: calc(-1 * var(--space-6));
  z-index: 10;
  border-radius: var(--radius-md) var(--radius-md) 0 0;
  background: var(--sage-50);
  box-shadow: 0 1px 0 var(--border-card), 0 8px 16px rgb(5 48 25 / 8%);
}

.stream-health-activity {
  margin-top: var(--space-5);
  padding-top: var(--space-4);
  border-top: 1px solid var(--border-card);
}

.source-template-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.source-template-heading h3,
.source-template-heading p {
  margin: 0;
}

.source-template-heading p {
  margin-top: var(--space-1);
  color: var(--text-muted);
  font-size: var(--fs-xs);
}

.source-template-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
  margin: var(--space-4) 0;
}

.source-template-summary div {
  display: grid;
  gap: var(--space-1);
  padding: var(--space-3);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-sm);
  background: var(--surface-sage);
}

.source-template-summary dt,
.source-flow__heading span,
.source-flow__stats dt,
.source-flow__sinks h5 {
  color: var(--text-muted);
  font-size: var(--fs-xs);
}

.source-template-summary dd,
.source-flow__stats dd {
  margin: 0;
  color: var(--text-heading);
  font-weight: var(--fw-bold);
}

.source-template-identity {
  margin-bottom: var(--space-4);
}

.source-flow-list {
  display: grid;
  gap: var(--space-3);
}

.source-flow {
  display: grid;
  gap: var(--space-4);
  padding: var(--space-4);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-md);
  background: var(--surface-sage);
}

.source-flow__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}

.source-flow__heading h4 {
  margin: var(--space-1) 0;
  color: var(--text-heading);
  font-size: var(--fs-base);
}

.source-flow__heading code,
.source-flow__revision-details code {
  overflow-wrap: anywhere;
}

.source-flow__revision {
  flex: 0 0 auto;
  padding: var(--space-1) var(--space-2);
  border: 1px solid currentColor;
  border-radius: var(--radius-pill);
  font-weight: var(--fw-bold);
}

.source-flow__revision--matched {
  color: var(--success) !important;
  background: #e4f1ea;
}

.source-flow__revision--changed {
  color: var(--warning) !important;
  background: #fbf1de;
}

.source-flow__notice {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--fs-xs);
}

.source-flow__stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
  margin: 0;
}

.source-flow__stats div {
  display: grid;
  align-content: start;
  gap: var(--space-1);
  min-width: 0;
  padding: var(--space-3);
  border-left: var(--border-accent) solid var(--accent);
  background: var(--surface-card);
}

.source-flow__stats dd {
  overflow-wrap: anywhere;
}

.source-flow__sinks {
  display: grid;
  gap: var(--space-2);
}

.source-flow__sinks h5,
.source-flow__sinks p {
  margin: 0;
}

.source-flow__sinks ul {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.source-flow__sinks li {
  display: flex;
  align-items: baseline;
  gap: var(--space-2) var(--space-3);
  flex-wrap: wrap;
  padding: var(--space-3);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-sm);
  background: var(--surface-card);
  font-size: var(--fs-xs);
}

.source-flow__sinks li span,
.source-flow__sinks li code {
  color: var(--text-muted);
}

.source-flow__revision-details summary,
.source-snapshot summary {
  cursor: pointer;
  font-weight: var(--fw-bold);
}

.session-summary__overview {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-4);
  margin-top: var(--space-2);
}

.session-summary__details,
.session-summary__overview .session-rat {
  margin: 0;
}

.session-summary__overview .session-rat {
  min-width: 10rem;
}

.note-timestamp-option {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.note-timestamp-option input {
  width: auto;
}

.note-character-count {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--fs-xs);
  text-align: right;
}

.source-snapshot {
  margin-top: var(--space-3);
}

.source-snapshot summary {
  margin-bottom: var(--space-2);
}

.source-snapshot p {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--fs-xs);
}

.source-snapshot pre {
  max-height: 22rem;
  overflow: auto;
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--surface-sage);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.recovery-story__heading,
.recovery-output__summary {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}

.recovery-story__heading h3,
.recovery-story__heading p,
.recovery-output__summary strong,
.recovery-output__summary span {
  display: block;
  margin: 0;
}

.recovery-output {
  display: grid;
  gap: var(--space-4);
  padding-block: var(--space-4);
  border-top: 1px solid var(--border-card);
}

.recovery-output__metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-3);
  margin: 0;
}

.recovery-output__metrics div,
.canonical-output,
.recovery-components li {
  display: grid;
  gap: var(--space-1);
}

.recovery-output__metrics dt,
.canonical-output span,
.recovery-components span {
  color: var(--text-muted);
  font-size: var(--fs-xs);
}

.recovery-output__metrics dd {
  margin: 0;
  color: var(--text-heading);
  font-weight: var(--fw-bold);
}

.canonical-output {
  padding: var(--space-3);
  border-left: var(--border-accent) solid var(--accent);
  background: var(--sage-50);
}

.canonical-output code,
.recovery-components code {
  overflow-wrap: anywhere;
}

.recovery-components summary {
  cursor: pointer;
  font-weight: var(--fw-bold);
}

.recovery-components ol {
  display: grid;
  gap: var(--space-3);
  margin-bottom: 0;
  padding-left: var(--space-5);
}

@media (max-width: 760px) {
  .detail-tabs {
    top: -1rem;
  }

  .session-summary__overview {
    grid-template-columns: 1fr;
  }

  .session-summary__overview .session-rat {
    min-width: 0;
  }

  .recovery-story__heading,
  .recovery-output__summary {
    display: grid;
  }

  .recovery-output__metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .source-template-summary,
  .source-flow__stats {
    grid-template-columns: 1fr;
  }

  .source-flow__heading {
    display: grid;
  }

  .source-flow__revision {
    width: fit-content;
  }
}

</style>
