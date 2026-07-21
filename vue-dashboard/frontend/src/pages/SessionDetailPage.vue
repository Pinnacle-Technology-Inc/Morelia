<script setup>
import { computed, ref } from "vue";
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
import LivePlot from "../components/LivePlot.vue";
import StatusBadge from "../components/StatusBadge.vue";
import TabBar from "../components/TabBar.vue";
import { deviceFlows, incidents } from "../data";
import { getSessionDeviceFlows } from "../overview-utils";

const props = defineProps({ session: { type: Object, required: true } });
defineEmits(["back"]);

const activeTab = ref("overview");
const dialog = ref(null);
const duplicateMode = ref("Copy device identity");
const duplicateName = ref(`${props.session.name} Copy`);
const sessionDeviceFlows = computed(() => getSessionDeviceFlows(deviceFlows, props.session.id));
const collection = computed(() => {
  if (props.session.lifecycle === "Active") return "Running";
  if (props.session.lifecycle === "Completed") return "Closed";
  return "Idle";
});

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

/** Translate mock/API sink shapes into Plot targets (type plot only). */
const plotTargets = computed(() => {
  const targets = [];
  for (const flow of sessionDeviceFlows.value) {
    for (const sink of flow.sinks ?? []) {
      if (!sinkIsPlot(sink)) continue;
      targets.push({
        key: `${flow.id}:${sink.sink_id ?? sink.sinkId ?? sink.name}`,
        sessionId: normalizeSessionId(props.session.id),
        sinkId: String(sink.sink_id ?? sink.sinkId ?? sink.name),
        sinkName: sink.name ?? sink.sinkId ?? "Browser plot",
        sinkHealth: sink.health ?? "Unknown",
        device: flow.device,
      });
    }
  }
  // Mock deviceFlows still use untyped {name,path,health}. Until the session
  // API returns typed Plot sinks, Active sessions expose one browser-plot
  // target per first stream so the live view is reachable for packet 28.
  if (!targets.length && props.session.lifecycle === "Active" && sessionDeviceFlows.value.length) {
    const flow = sessionDeviceFlows.value[0];
    targets.push({
      key: `${flow.id}:browser-plot`,
      sessionId: normalizeSessionId(props.session.id),
      sinkId: `${flow.hardwareId}:browser-plot`,
      sinkName: "Browser plot",
      sinkHealth: flow.health ?? "Unknown",
      device: flow.device,
    });
  }
  return targets;
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

const activity = [
  { time: "08:48", title: "Heartbeat confirmed on M32-007", tone: "green" },
  { time: "07:11", title: "Recovery verified - sink resumed after NFS stall", tone: "green" },
  { time: "07:10", title: "Reconnect submitted to session monitor", tone: "blue" },
  { time: "07:08", title: "Incident detected: NFS mount latency spike", tone: "amber" },
  { time: "06:14", title: "Session transitioned to Active", tone: "green" },
];

function sinkSummary(flow) {
  const healthyCount = flow.sinks.filter((sink) => sink.health === "Healthy").length;
  return `${healthyCount}/${flow.sinks.length} sinks healthy`;
}
</script>

<template>
  <div class="page page--detail">
    <button class="back-link" type="button" @click="$emit('back')"><ArrowLeft :size="16" /> Sessions</button>
    <header class="detail-header">
      <div>
        <div class="title-row">
          <h1>{{ session.name }}</h1>
          <StatusBadge :value="session.lifecycle" />
          <StatusBadge :value="session.health" />
        </div>
        <p v-if="session.experiment"><FlaskConical :size="16" /> {{ session.experiment }}</p>
        <div class="detail-metadata">
          <code>{{ session.duration ?? "Not started" }}</code>
          <span>{{ session.streamCount ?? session.deviceCount }} streams / {{ session.sinkCount }} sinks</span>
          <StatusBadge compact :value="session.watchdog" />
          <span>Last update 0s ago</span>
        </div>
      </div>
      <div class="detail-actions">
        <BaseButton variant="secondary"><FilePlus2 :size="16" /> Add Note</BaseButton>
        <BaseButton variant="secondary" @click="dialog = 'duplicate'"><Copy :size="16" /> Duplicate</BaseButton>
        <BaseButton v-if="session.lifecycle === 'Active'" variant="secondary"><CheckCircle2 :size="16" /> Complete</BaseButton>
        <BaseButton v-if="session.lifecycle === 'Active'" variant="danger" @click="dialog = 'stop'"><StopCircle :size="16" /> Stop</BaseButton>
      </div>
    </header>

    <div v-if="session.health === 'Needs action'" class="detail-alert">
      <AlertTriangle :size="18" />
      <span>{{ session.attentionReason }}</span>
      <button type="button" @click="activeTab = 'recovery'">Review in Recovery</button>
    </div>

    <BaseCard class="detail-content">
      <TabBar :tabs="visibleTabs" :active="activeTab" @change="activeTab = $event" />

      <div v-if="activeTab === 'overview'" class="detail-grid">
        <BaseCard class="detail-panel">
          <h3>Session Summary</h3>
          <dl class="detail-list">
            <div><dt>Lifecycle</dt><dd>{{ session.lifecycle }}</dd></div>
            <div><dt>Session Health</dt><dd>{{ session.health }}</dd></div>
            <div><dt>Collection</dt><dd>{{ collection }}</dd></div>
            <div><dt>Experiment</dt><dd>{{ session.experiment ?? "Ungrouped" }}</dd></div>
            <div><dt>Ownership</dt><dd>{{ session.isOwner ? "Owner session" : "Monitoring only" }}</dd></div>
          </dl>
        </BaseCard>
        <BaseCard class="detail-panel">
          <h3>Current Recovery</h3>
          <p v-if="session.health === 'Needs action'">A guarded recovery recommendation is waiting for operator approval.</p>
          <p v-else>No active recovery. Required verification checks are passing.</p>
          <BaseButton v-if="session.health === 'Needs action'" @click="dialog = 'approve'"><Shield :size="16" /> Review Action</BaseButton>
        </BaseCard>
        <BaseCard class="detail-panel detail-panel--wide">
          <h3>Stream Health</h3>
          <div class="flow-summary-grid">
            <div v-for="flow in sessionDeviceFlows" :key="flow.id">
              <strong>{{ flow.device }}</strong><code>{{ flow.hardwareId }}</code>
              <StatusBadge :value="flow.health" />
              <span>{{ flow.rate }} · Last data {{ flow.lastData }} · {{ sinkSummary(flow) }}</span>
            </div>
          </div>
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
          <p>
            Presentation-only view for configured Plot sinks. Lag and drops here are sink-local and
            never rewrite source health.
          </p>
        </BaseCard>
        <LivePlot
          v-for="target in plotTargets"
          :key="target.key"
          :session-id="target.sessionId"
          :sink-id="target.sinkId"
          :sink-name="`${target.device} · ${target.sinkName}`"
          :sink-health="target.sinkHealth"
          :auto-start="session.lifecycle === 'Active'"
        />
        <BaseCard v-if="!plotTargets.length" class="detail-panel">
          <p>No Plot sinks are configured on this session.</p>
        </BaseCard>
      </div>

      <div v-else-if="activeTab === 'recovery'" class="recovery-layout">
        <BaseCard class="detail-panel"><h3>Assigned Policy</h3><dl class="detail-list"><div><dt>Policy</dt><dd>Recommend</dd></div><div><dt>Verification</dt><dd>Device, sink, data rate</dd></div></dl></BaseCard>
        <BaseCard class="detail-panel">
          <h3>Recovery Activity</h3>
          <div class="phase-list"><span class="done">Validate</span><span class="current">Recover</span><span>Verify</span></div>
          <div class="card-actions">
            <BaseButton @click="dialog = 'approve'"><Play :size="16" /> Approve Recovery</BaseButton>
            <BaseButton variant="secondary">Retry Recovery</BaseButton>
            <BaseButton variant="secondary">Mark Resolved</BaseButton>
          </div>
        </BaseCard>
      </div>

      <div v-else-if="activeTab === 'incidents'" class="table-wrap">
        <table class="data-table"><thead><tr><th>Time</th><th>Stream</th><th>Reason</th><th>Policy</th><th>Outcome</th><th>State</th></tr></thead><tbody><tr v-for="incident in incidents.filter(item => item.sessionId === session.id)" :key="incident.id"><td><code>{{ incident.time }}</code></td><td><code>{{ incident.stream }}</code></td><td>{{ incident.reason }}</td><td>Recommend</td><td>{{ incident.outcome }}</td><td>{{ incident.resolved ? "Resolved" : "Open" }}</td></tr></tbody></table>
      </div>

      <div v-else-if="activeTab === 'activity'">
        <div class="detail-tab-actions"><BaseButton variant="secondary"><FilePlus2 :size="16" /> Add Note</BaseButton><BaseButton variant="secondary">Filter</BaseButton></div>
        <div class="timeline"><div v-for="item in activity" :key="item.time + item.title"><code>{{ item.time }}</code><i :class="`dot--${item.tone}`" /><p>{{ item.title }}</p></div></div>
      </div>

      <div v-else class="configuration-grid">
        <BaseCard class="detail-panel"><h3>Metadata</h3><dl class="detail-list"><div><dt>Name</dt><dd>{{ session.name }}</dd></div><div><dt>Experiment</dt><dd>{{ session.experiment ?? "None" }}</dd></div><div><dt>Schedule</dt><dd>{{ session.scheduledTime ? "One-time" : "Manual" }}</dd></div><div><dt>Recovery Policy</dt><dd>Recommend</dd></div></dl></BaseCard>
        <BaseCard class="detail-panel"><h3>Runtime Lock</h3><p>{{ session.lifecycle === "Draft" ? "Configuration is editable before start." : "Stream and sink configuration is read-only after start." }}</p></BaseCard>
      </div>
    </BaseCard>

    <GuardedDialog v-if="dialog === 'stop'" title="Stop Session" description="This will stop the session through the session monitor." confirm-label="Stop Session" danger @close="dialog = null" @confirm="dialog = null">
      <div class="dialog-notice"><strong>Streams affected</strong><code v-for="flow in sessionDeviceFlows" :key="flow.id">{{ flow.device }}</code></div>
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
