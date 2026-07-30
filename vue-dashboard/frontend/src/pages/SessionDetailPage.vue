<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Copy,
  ExternalLink,
  FilePlus2,
  FlaskConical,
  FolderPen,
  Play,
  Shield,
  StopCircle,
} from "@lucide/vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import CollapsibleSection from "../components/CollapsibleSection.vue";
import FolderPickerDialog from "../components/FolderPickerDialog.vue";
import GuardedDialog from "../components/GuardedDialog.vue";
import RatRunIndicator from "../components/RatRunIndicator.vue";
import SessionFlowBar from "../components/SessionFlowBar.vue";
import StatusBadge from "../components/StatusBadge.vue";
import TabBar from "../components/TabBar.vue";
import { completeSession, loadSinkPlan, normalizeSession, startSession, stopSession } from "../session-api";
import { loadSessionDetail } from "../session-detail-api";
import { createSessionEventStream, SessionEventState } from "../session-events";
import {
  deriveFlowStatus,
  deriveRatState,
  deriveStreamRows,
  isOutboxUnproven,
} from "../session-flow-status";
import { isRunningLifecycle } from "../session-utils";

// `session` is an OPTIONAL fast-path only: the catalog row, when the operator
// arrived from the sessions list. This page resolves everything it needs from
// `sessionId` alone via GET /sessions/<id>/status, whose response is a superset
// of the catalog row. That is what lets a just-created session be deep-linked
// straight from the Create wizard, before any list has been refetched.
const props = defineProps({
  session: { type: Object, default: null },
  sessionId: { type: [String, Number], required: true },
});
const emit = defineEmits(["back", "state-changed"]);

const activeTab = ref("overview");
const dialog = ref(null);
const duplicateMode = ref("Copy device identity");
const duplicateName = ref("");
const detail = ref(null);
const detailState = ref("loading");
const detailError = ref("");
const commandError = ref("");
const commandBusy = ref(false);
// File sinks the operator must name before a stopped session restarts, plus
// the ones the backend names on its own (shown, but not editable).
const restartSinks = ref([]);
const restartAutoNamed = ref([]);
const restartFolderPickerKey = ref(null);
const activity = ref({ state: SessionEventState.IDLE, events: [], error: null });
// Optimistic lifecycle from a just-issued command, shown until the refetch that
// follows it lands. Cleared by refreshDetail() so the server always wins.
const pendingLifecycle = ref(null);
let eventStream;
let pollTimer = null;

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

const lifecycle = computed(() => pendingLifecycle.value ?? view.value.lifecycle);

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
        path: sink.output?.path,
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
      lastData: detail.value?.latest_report?.received_at ?? "Unavailable",
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
const dataPathIncidents = computed(() =>
  detailIncidents.value.filter((incident) => incident.axis !== "control_plane"),
);
const controlPlaneIncidents = computed(() =>
  detailIncidents.value.filter((incident) => incident.axis === "control_plane"),
);
const detailGaps = computed(() => detail.value?.gaps ?? []);
// Already fetched on every poll and, until now, dropped on the floor.
const detailOperations = computed(() => detail.value?.operations ?? []);

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

const openDataPathIncidents = computed(() => dataPathIncidents.value.filter(isOpenIncident));
const openControlPlaneIncidents = computed(() =>
  controlPlaneIncidents.value.filter(isOpenIncident),
);
// Badge inputs — a strict subset of the tables above, which still show
// everything unresolved so a self-healing condition stays visible while it heals.
const actionableDataPathIncidents = computed(() =>
  dataPathIncidents.value.filter(isWaitingOnOperator),
);
const actionableControlPlaneIncidents = computed(() =>
  controlPlaneIncidents.value.filter(isWaitingOnOperator),
);

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
  const incidents = openDataPathIncidents.value.length > 0;
  const gaps = detailGaps.value.length > 0;
  const controlPlane = openControlPlaneIncidents.value.length > 0;
  const commands = detailOperations.value.length > 0;
  return {
    incidents: incidents || !gaps,
    gaps: gaps && !incidents,
    controlPlane: controlPlane || !commands,
    commands: commands && !controlPlane,
  };
});

const detailUnavailable = computed(() => detailState.value === "unavailable");

// The rat (in Session Summary) and the rail (in Stream Health) are now in
// different cards but must never disagree, so both resolve from ONE set of
// inputs: this object is bound onto SessionFlowBar and fed to deriveFlowStatus
// for the rat. Restating the argument list at either call site is what would let
// a running rat end up beside a red rail.
const flowInputs = computed(() => ({
  lifecycle: lifecycle.value,
  health: view.value.health,
  phase: view.value.phase,
  activityState: activity.value.state,
  detailAvailable: !detailUnavailable.value,
  streams: streamRows.value,
  outboxHealth: detail.value?.outbox_health ?? null,
}));

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
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
}

// While spectating, /status is re-read on a slow timer AND opportunistically
// whenever the event stream delivers something new. The timer alone would lag a
// state change by up to its interval; the event trigger alone would go blind if
// the SSE connection dropped. Together the bar stays honest under both failures.
const DETAIL_POLL_MS = 5000;
const EVENT_REFRESH_THROTTLE_MS = 2000;
let lastDetailFetch = 0;

/** `silent` keeps a background refresh from flashing the page back to loading. */
async function refreshDetail({ silent = false } = {}) {
  if (!silent) detailState.value = "loading";
  lastDetailFetch = Date.now();
  try {
    detail.value = await loadSessionDetail(props.sessionId);
    detailState.value = "live";
    detailError.value = "";
    // The server has now spoken; drop any optimistic post-command lifecycle.
    pendingLifecycle.value = null;
  } catch (error) {
    // A failed *background* refresh keeps the last good snapshot on screen —
    // blanking a live view because one poll missed is worse than mild staleness.
    if (!silent) detail.value = null;
    detailState.value = "unavailable";
    detailError.value = error instanceof Error ? error.message : "Session detail is unavailable.";
  }
}

function onActivitySnapshot(snapshot) {
  const grew = snapshot.events.length > activity.value.events.length;
  activity.value = snapshot;
  if (grew && Date.now() - lastDetailFetch >= EVENT_REFRESH_THROTTLE_MS) {
    refreshDetail({ silent: true });
  }
}

onMounted(() => {
  refreshDetail();
  eventStream = createSessionEventStream({
    sessionId: props.sessionId,
    onChange: onActivitySnapshot,
  });
  eventStream.start();
  // Resting sessions (Draft/Stopped/Completed) only change through this page's
  // own commands, which refetch directly — no need to poll those.
  pollTimer = setInterval(() => {
    if (isRunningLifecycle(lifecycle.value) || lifecycle.value === "Unknown") {
      refreshDetail({ silent: true });
    }
  }, DETAIL_POLL_MS);
});
onUnmounted(() => {
  eventStream?.stop();
  if (pollTimer) clearInterval(pollTimer);
});

function applyCommandResult(result) {
  const labels = { draft: "Draft", scheduled: "Scheduled", starting: "Starting", active: "Active", ending: "Ending", stopped: "Stopped", completed: "Completed" };
  if (result?.status && labels[result.status]) pendingLifecycle.value = labels[result.status];
  emit("state-changed", result);
}

function openDuplicate() {
  duplicateName.value = `${view.value.name} Copy`;
  dialog.value = "duplicate";
}

async function runLifecycleCommand(command) {
  commandBusy.value = true;
  commandError.value = "";
  try {
    const result = await command();
    applyCommandResult(result);
    dialog.value = null;
    await refreshDetail();
  } catch (error) {
    commandError.value = error instanceof Error ? error.message : "The lifecycle command failed.";
  } finally {
    commandBusy.value = false;
  }
}

function confirmStop() {
  return runLifecycleCommand(() => stopSession(props.sessionId));
}

// A stopped session's file sinks still point at the files the previous run
// wrote, and a managed output file is never reopened or overwritten. So the
// restart asks for the output names FIRST rather than letting start fail with
// a 409 the operator then has to interpret.
async function restartStopped() {
  commandError.value = "";
  const autoNamed = [];
  const named = [];
  try {
    const plan = await loadSinkPlan(props.sessionId);
    for (const sink of plan?.sinks ?? []) {
      if (sink.assignment === "explicit") named.push(sink);
      else autoNamed.push(sink);
    }
  } catch (error) {
    commandError.value =
      error instanceof Error ? error.message : "Could not read this session's output plan.";
    return;
  }

  // Nothing to name (service/plot sinks only, or every path auto-assigned):
  // start straight away rather than showing an empty dialog.
  if (!named.length) return runLifecycleCommand(() => startSession(props.sessionId));

  restartSinks.value = named.map((sink) => ({
    ...sink,
    location: sink.suggested_location ?? sink.current_location ?? "",
  }));
  restartAutoNamed.value = autoNamed;
  dialog.value = "restart";
}

const restartOverrides = computed(() =>
  Object.fromEntries(
    restartSinks.value
      .filter((sink) => sink.location && sink.location !== sink.current_location)
      .map((sink) => [sink.key, sink.location]),
  ),
);

// Reusing a path the previous run already wrote would be rejected at start
// anyway; catching it here keeps the operator in the dialog they're already in.
const restartReusedPaths = computed(() =>
  restartSinks.value.filter((sink) => sink.occupied && sink.location === sink.current_location),
);

const restartBlocked = computed(
  () => restartReusedPaths.value.length > 0 || restartSinks.value.some((sink) => !sink.location.trim()),
);

function splitOutputLocation(location) {
  const value = String(location ?? "");
  const boundary = Math.max(value.lastIndexOf("/"), value.lastIndexOf("\\"));
  if (boundary < 0) return { folder: "", filename: value };
  return { folder: value.slice(0, boundary), filename: value.slice(boundary + 1) };
}

function openRestartFolderPicker(sink) {
  restartFolderPickerKey.value = sink.key;
}

const restartFolderPickerFolder = computed(() => {
  const sink = restartSinks.value.find((entry) => entry.key === restartFolderPickerKey.value);
  return splitOutputLocation(sink?.location).folder;
});

function chooseRestartFolder(folder) {
  const sink = restartSinks.value.find((entry) => entry.key === restartFolderPickerKey.value);
  if (!sink) return;
  const filename = splitOutputLocation(sink.location).filename || `${sink.sink_name}.${sink.sink_type}`;
  const separator = folder.includes("\\") ? "\\" : "/";
  sink.location = `${folder.replace(/[\\/]$/, "")}${separator}${filename}`;
  restartFolderPickerKey.value = null;
}

function confirmRestart() {
  if (restartBlocked.value) return;
  return runLifecycleCommand(() =>
    startSession(props.sessionId, { sinkOverrides: restartOverrides.value }),
  );
}

function sinkIsPlot(sink) {
  const type = sink.type ?? sink.sink_type ?? sink.sinkClass ?? sink.sink_class;
  return (
    type === "plot" ||
    /plot/i.test(String(sink.name ?? "")) ||
    /plot/i.test(String(sink.path ?? ""))
  );
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
  { id: "incidents", label: "Incidents & Gaps" },
  { id: "operations", label: "Operations" },
  { id: "activity", label: "Activity & Notes" },
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
  if (actionableDataPathIncidents.value.length) {
    counts.incidents = actionableDataPathIncidents.value.length;
  }
  // Only self-healing FAILURES badge here: a watchdog that crashed and respawned
  // is history, not a task. Crash loop (respawn budget spent) and outbox overflow
  // (telemetry not draining) are the cases the system could not fix itself.
  if (actionableControlPlaneIncidents.value.length) {
    counts.operations = actionableControlPlaneIncidents.value.length;
  }
  if (detail.value?.recovery) counts.recovery = 1;
  return counts;
});

const tabTones = computed(() => ({
  streams: streamRows.value.some((row) => row.tone === "bad") ? "bad" : "warn",
  incidents: actionableDataPathIncidents.value.length ? "bad" : "warn",
  operations: actionableControlPlaneIncidents.value.length ? "bad" : "warn",
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
        <BaseButton v-if="lifecycle !== 'Completed'" variant="secondary"><FilePlus2 :size="16" /> Add Note</BaseButton>
        <BaseButton v-if="lifecycle !== 'Completed'" variant="secondary" @click="openDuplicate"><Copy :size="16" /> Duplicate</BaseButton>
        <BaseButton v-if="lifecycle === 'Stopped'" variant="secondary" :disabled="commandBusy" @click="dialog = 'complete'"><CheckCircle2 :size="16" /> Complete</BaseButton>
        <BaseButton v-if="lifecycle === 'Stopped'" variant="primary" :disabled="commandBusy" @click="restartStopped"><Play :size="16" /> Start</BaseButton>
        <BaseButton v-if="isRunningLifecycle(lifecycle)" variant="danger" :disabled="commandBusy" @click="dialog = 'stop'"><StopCircle :size="16" /> Stop</BaseButton>
        <p v-if="commandError" class="form-notice">{{ commandError }}</p>
      </div>
    </header>

    <BaseCard class="detail-content">
      <TabBar
        :tabs="visibleTabs"
        :active="activeTab"
        :counts="tabCounts"
        :tones="tabTones"
        @change="activeTab = $event"
      />

      <div v-if="activeTab === 'overview'" class="detail-grid">
        <BaseCard class="detail-panel">
          <h3>Session Summary</h3>
          <!-- The session verdict leads the card so an operator can scan its
               current state before reading the supporting configuration. -->
          <div class="session-rat">
            <RatRunIndicator :state="ratState" size="lg" />
            <p :class="`session-rat__caption session-rat__caption--${ratState}`">{{ ratCaption }}</p>
          </div>
          <dl class="detail-list">
            <div><dt>Ownership</dt><dd>{{ view.isOwner ? "Owner session" : "Monitoring only" }}</dd></div>
            <div><dt>Experiment</dt><dd>{{ view.experiment ?? "Ungrouped" }}</dd></div>
          </dl>
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
            :events="activity.events"
            :detail-error="detailError"
            :last-report-at="detail?.latest_report?.received_at ?? null"
          />
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
        <BaseCard class="detail-panel"><h3>Assigned Policy</h3><dl class="detail-list"><div><dt>Policy</dt><dd>Recommend</dd></div><div><dt>Verification</dt><dd>Device, sink, data rate</dd></div></dl></BaseCard>
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
      </div>

      <!-- Two surfaces, not one merged list. The incidents table is what is
           waiting on a person right now; the gap log is a permanent record of
           missing data that nobody has to act on. Merging them meant a gap
           carrying a linked incident_id rendered under the INCIDENT's id — so
           its own gap_id was never shown anywhere and both rows shared a Vue
           key. Each table now keys on its own identifier. -->
      <div v-else-if="activeTab === 'incidents'" class="records-layout">
        <BaseCard v-if="detailUnavailable" class="detail-panel">
          <p class="records-empty">Incidents and gaps are unavailable.</p>
        </BaseCard>
        <template v-else>
          <BaseCard class="detail-panel detail-panel--records">
            <CollapsibleSection
              title="Needs action"
              hint="Unresolved incidents on the data path"
              :count="openDataPathIncidents.length"
              :tone="actionableDataPathIncidents.length ? 'bad' : 'neutral'"
              :default-open="openSections.incidents"
            >
              <p v-if="!openDataPathIncidents.length" class="records-empty">
                Nothing is waiting on you. Streams recovering on their own are not listed here —
                they appear in the gap log once the episode closes.
              </p>
              <div v-else class="table-wrap">
                <table class="data-table records-table">
                  <thead>
                    <tr><th>Incident</th><th>Device</th><th>Sink</th><th>Reason</th><th>Why now</th><th>State</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="incident in openDataPathIncidents" :key="incident.incident_id">
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
              title="Recovery gaps"
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
                      <td>{{ gapWindow(gap) }}</td>
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

      <!-- The control-plane surface: what the machinery did, as opposed to what
           happened to the data. The operations payload has been arriving on
           every poll since this page was written and was never rendered. -->
      <div v-else-if="activeTab === 'operations'" class="records-layout">
        <BaseCard v-if="detailUnavailable" class="detail-panel">
          <p class="records-empty">Operations are unavailable.</p>
        </BaseCard>
        <template v-else>
          <BaseCard class="detail-panel detail-panel--records">
            <CollapsibleSection
              title="Control-plane incidents"
              hint="Processes, telemetry and failed commands"
              :count="openControlPlaneIncidents.length"
              :tone="actionableControlPlaneIncidents.length ? 'bad' : 'neutral'"
              :default-open="openSections.controlPlane"
            >
              <p v-if="!openControlPlaneIncidents.length" class="records-empty">
                No open control-plane incidents.
              </p>
              <div v-else class="table-wrap">
                <table class="data-table records-table">
                  <thead>
                    <tr><th>Incident</th><th>Reason</th><th>Opened</th><th>Waiting on</th><th>State</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="incident in openControlPlaneIncidents" :key="incident.incident_id">
                      <td><code>{{ incident.incident_id }}</code></td>
                      <td>{{ incident.reason }}</td>
                      <td>{{ formatTimestamp(incident.opened_at) }}</td>
                      <!-- Named explicitly rather than implied by a badge: a crashed
                           watchdog respawning itself and a spent respawn budget look
                           identical in a status column, and only one wants you. -->
                      <td>{{ incident.needs_action === false ? "System — recovering itself" : "You" }}</td>
                      <td><StatusBadge compact :value="formatStatus(incident.status)" /></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </CollapsibleSection>
          </BaseCard>

          <BaseCard class="detail-panel detail-panel--records">
            <CollapsibleSection
              title="Commands"
              hint="Durable log of every command issued against this session"
              :count="detailOperations.length"
              :default-open="openSections.commands"
            >
              <p v-if="!detailOperations.length" class="records-empty">
                No operations have been recorded for this session.
              </p>
              <div v-else class="table-wrap">
                <table class="operations-table data-table records-table">
                  <thead>
                    <tr><th>Operation</th><th>Command</th><th>Target</th><th>State</th><th>Finished</th><th>Error</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="operation in detailOperations" :key="operation.operation_id">
                      <td><code>{{ operation.operation_id }}</code></td>
                      <td>{{ operation.command }}</td>
                      <td><code>{{ operation.target_device_id ?? operation.scope }}</code></td>
                      <td><StatusBadge compact :value="formatStatus(operation.state)" /></td>
                      <td>{{ formatTimestamp(operation.finished_at) }}</td>
                      <td>{{ operation.error_message ?? "—" }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </CollapsibleSection>
          </BaseCard>
        </template>
      </div>

      <div v-else-if="activeTab === 'activity'">
        <div class="detail-tab-actions"><BaseButton variant="secondary"><FilePlus2 :size="16" /> Add Note</BaseButton><BaseButton variant="secondary">Filter</BaseButton></div>
        <p v-if="activity.state === 'unavailable' || activity.state === 'stale'" class="detail-alert">Activity is {{ activity.state }}. Showing only the last proven events.</p>
        <p v-else-if="!activity.events.length">No activity events have been received yet.</p>
        <div v-else class="phase-list"><div v-for="event in activity.events" :key="event.id ?? `${event.type}-${event.data.sequence}`"><code>#{{ event.id ?? "—" }}</code><strong>{{ event.type }}</strong><span>{{ event.data.phase ?? event.data.message ?? "Event received" }}</span></div></div>
      </div>

      <div v-else class="configuration-grid">
        <BaseCard class="detail-panel"><h3>Metadata</h3><dl class="detail-list"><div><dt>Name</dt><dd>{{ view.name }}</dd></div><div><dt>Experiment</dt><dd>{{ view.experiment ?? "None" }}</dd></div><div><dt>Schedule</dt><dd>{{ view.scheduledTime ? "One-time" : "Manual" }}</dd></div><div><dt>Recovery Policy</dt><dd>{{ view.policy ?? "Recommend" }}</dd></div></dl></BaseCard>
        <BaseCard class="detail-panel"><h3>Runtime Lock</h3><p>{{ lifecycle === "Draft" ? "Configuration is editable before start." : "Stream and sink configuration is read-only after start." }}</p></BaseCard>
      </div>
    </BaseCard>

    <GuardedDialog v-if="dialog === 'stop'" title="Stop Session" description="This concludes the current dataflow and output generation. The session remains restartable." confirm-label="Stop Session" danger @close="dialog = null" @confirm="confirmStop">
      <div class="dialog-notice"><strong>Streams affected</strong><code v-for="flow in sessionDeviceFlows" :key="flow.id">{{ flow.device }}</code></div>
    </GuardedDialog>
    <GuardedDialog v-if="dialog === 'complete'" title="Complete Session" description="This permanently archives the stopped session. Future Start, Stop, Recover, and configuration mutations are prohibited." confirm-label="Complete Session" danger @close="dialog = null" @confirm="() => runLifecycleCommand(() => completeSession(props.sessionId))">
      <div class="dialog-notice"><strong>Terminal action</strong><span>The completed session remains read-only history.</span></div>
    </GuardedDialog>
    <GuardedDialog v-if="dialog === 'approve'" title="Approve Recovery Action" description="Policy: Recommend" confirm-label="Approve Recovery" @close="dialog = null" @confirm="dialog = null">
      <dl class="detail-list"><div><dt>Detected problem</dt><dd>Heartbeat timeout - 15 s silence</dd></div><div><dt>Proposed action</dt><dd>Reconnect through guarded session monitor</dd></div><div><dt>Expected interruption</dt><dd>About 8 s data gap</dd></div><div><dt>Required verification</dt><dd>Device health, sink access, data rate</dd></div></dl>
    </GuardedDialog>
    <GuardedDialog
      v-if="dialog === 'restart'"
      title="Start Session Again"
      description="Each run writes its own output files. Name the outputs for this run."
      confirm-label="Start Session"
      @close="dialog = null"
      @confirm="confirmRestart"
    >
      <div class="dialog-form">
        <label v-for="sink in restartSinks" :key="sink.key" class="field">
          <span>{{ sink.nickname ? `${sink.nickname} — ${sink.sink_name}` : sink.sink_name }} ({{ sink.sink_type }})</span>
          <div class="restart-location-control">
            <input v-model="sink.location" spellcheck="false" />
            <BaseButton variant="secondary" @click="openRestartFolderPicker(sink)">
              <FolderPen :size="15" /> Choose folder
            </BaseButton>
          </div>
          <small v-if="sink.occupied && sink.location === sink.current_location" class="form-notice">
            <AlertTriangle :size="16" /> The previous run's file is still here. Choose a different name.
          </small>
          <small v-else-if="sink.occupied">Previous run: {{ sink.current_location }}</small>
        </label>
        <p v-if="restartAutoNamed.length" class="form-notice">
          {{ restartAutoNamed.length }} further output{{ restartAutoNamed.length === 1 ? " is" : "s are" }}
          named automatically at start.
        </p>
        <p v-if="restartBlocked" class="form-notice">
          <AlertTriangle :size="18" /> Give every output a name that isn't already taken.
        </p>
      </div>
    </GuardedDialog>
    <FolderPickerDialog
      v-if="restartFolderPickerKey"
      :model-value="restartFolderPickerFolder"
      @select="chooseRestartFolder"
      @close="restartFolderPickerKey = null"
    />
    <GuardedDialog v-if="dialog === 'duplicate'" title="Duplicate Session" confirm-label="Create Session" @close="dialog = null" @confirm="dialog = null">
      <div class="dialog-form">
        <label class="field"><span>Session Name</span><input v-model="duplicateName" /></label>
        <label class="field"><span>Device Copy Mode</span><select v-model="duplicateMode"><option>Copy device identity</option><option>Generic copy</option></select></label>
        <p v-if="duplicateMode === 'Generic copy'" class="form-notice"><AlertTriangle :size="18" /> Pick devices before starting this session.</p>
      </div>
    </GuardedDialog>
  </div>
</template>

<style scoped>
.restart-location-control {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.restart-location-control input {
  min-width: 0;
  flex: 1;
}
</style>
