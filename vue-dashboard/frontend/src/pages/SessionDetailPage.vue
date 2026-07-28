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
  Play,
  Shield,
  StopCircle,
} from "@lucide/vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import GuardedDialog from "../components/GuardedDialog.vue";
import RatRunIndicator from "../components/RatRunIndicator.vue";
import SessionFlowBar from "../components/SessionFlowBar.vue";
import StatusBadge from "../components/StatusBadge.vue";
import TabBar from "../components/TabBar.vue";
import { completeSession, normalizeSession, startSession, stopSession } from "../session-api";
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
const detailIncidents = computed(() => detail.value?.incidents ?? []);
const detailGaps = computed(() => detail.value?.gaps ?? []);
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

function restartStopped() {
  return runLifecycleCommand(() => startSession(props.sessionId));
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
  const openIssues = [...detailIncidents.value, ...detailGaps.value].length;
  if (openIssues) counts.incidents = openIssues;
  if (detail.value?.recovery) counts.recovery = 1;
  return counts;
});

const tabTones = computed(() => ({
  streams: streamRows.value.some((row) => row.tone === "bad") ? "bad" : "warn",
  incidents: detailIncidents.value.length ? "bad" : "warn",
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

      <div v-else-if="activeTab === 'incidents'" class="table-wrap">
        <p v-if="detailUnavailable">Incidents and gaps are unavailable.</p>
        <table v-else class="data-table"><thead><tr><th>Incident / Gap</th><th>Device</th><th>Reason</th><th>State</th></tr></thead><tbody><tr v-for="incident in [...detailIncidents, ...detailGaps]" :key="incident.incident_id ?? incident.gap_id"><td><code>{{ incident.incident_id ?? incident.gap_id }}</code></td><td><code>{{ incident.device_id }}</code></td><td>{{ incident.reason }}</td><td>{{ incident.status ?? incident.confidence ?? "Open" }}</td></tr></tbody></table>
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
    <GuardedDialog v-if="dialog === 'duplicate'" title="Duplicate Session" confirm-label="Create Session" @close="dialog = null" @confirm="dialog = null">
      <div class="dialog-form">
        <label class="field"><span>Session Name</span><input v-model="duplicateName" /></label>
        <label class="field"><span>Device Copy Mode</span><select v-model="duplicateMode"><option>Copy device identity</option><option>Generic copy</option></select></label>
        <p v-if="duplicateMode === 'Generic copy'" class="form-notice"><AlertTriangle :size="18" /> Pick devices before starting this session.</p>
      </div>
    </GuardedDialog>
  </div>
</template>
