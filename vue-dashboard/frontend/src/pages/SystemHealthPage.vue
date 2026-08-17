<script setup>
import { computed, onMounted, ref } from "vue";
import { Power, RefreshCw, ShieldAlert } from "@lucide/vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import PageHeader from "../components/PageHeader.vue";
import StatusBadge from "../components/StatusBadge.vue";
import TabBar from "../components/TabBar.vue";
import GuardedDialog from "../components/GuardedDialog.vue";
import { loadSystemHealth, reconcileRuntimes, restartControlPlane, shutdownControlPlane } from "../system-health-api";
import { formatCentralTimestamp } from "../datetime";

const activeTab = ref("session-monitors");
const tabs = [
  { id: "session-monitors", label: "Session Monitors" },
  { id: "streams", label: "Streams" },
  { id: "storage", label: "Storage" },
];
const healthState = ref("loading");
const healthError = ref("");
const health = ref(null);
const ready = ref(null);
const runtimes = ref([]);
const action = ref(null);
const actionBusy = ref(false);
const actionError = ref("");
const cascade = ref(false);

const backendProcessStatus = computed(() => {
  if (!ready.value) return "Unavailable";
  if (ready.value.ready !== true) return "Attention";
  const runtimeStates = runtimes.value.map((runtime) => String(runtime.state ?? "").toLowerCase());
  if (runtimeStates.some((state) => ["failed", "uncertain"].includes(state))) return "Attention";
  return "Ready";
});

onMounted(async () => {
  try {
    const result = await loadSystemHealth();
    health.value = result.health;
    ready.value = result.ready;
    runtimes.value = result.runtimes;
    healthError.value = result.errors.join("; ");
    healthState.value = result.errors.length ? "degraded" : "live";
  } catch (error) {
    healthState.value = "unavailable";
    healthError.value = error instanceof Error ? error.message : "System health is unavailable.";
  }
});

async function runAction(fn) {
  actionBusy.value = true;
  actionError.value = "";
  try { await fn(); action.value = null; } catch (error) { actionError.value = error instanceof Error ? error.message : "System action failed."; } finally { actionBusy.value = false; }
}
</script>

<template>
  <div class="page page--workspace">
    <PageHeader
      eyebrow="Infrastructure"
      title="System Health"
      description="Inspect session monitors, stream ownership, communication, and storage."
    />
    <section class="system-health-overview" aria-label="Control plane health">
      <BaseCard class="detail-panel">
        <div class="title-row"><h2>Daemon</h2><StatusBadge :value="health?.status === 'ok' ? 'Running' : 'Unavailable'" /></div>
        <dl class="detail-list">
          <div><dt>Status</dt><dd>{{ health?.status === "ok" ? "Liveness confirmed" : "Unavailable" }}</dd></div>
          <div><dt>Readiness</dt><dd v-if="ready">{{ ready.ready ? "Ready" : "Not ready" }} · {{ Object.keys(ready.checks ?? {}).length }} checks reported</dd><dd v-else>Unavailable</dd></div>
        </dl>
        <div class="daemon-actions">
          <BaseButton variant="secondary" :disabled="actionBusy" @click="action = 'reconcile'"><RefreshCw :size="16" /> Reconcile</BaseButton>
          <BaseButton variant="secondary" :disabled="actionBusy" @click="action = 'restart'"><RefreshCw :size="16" /> Restart Control Plane</BaseButton>
          <BaseButton variant="danger" :disabled="actionBusy" @click="action = 'shutdown'"><Power :size="16" /> Shutdown</BaseButton>
          <label class="cascade-option"><input v-model="cascade" type="checkbox" /> Force runtime shutdown</label>
        </div>
        <p class="helper-copy">Runtime agents self-terminate after about 30 minutes without daemon contact.</p>
      </BaseCard>
      <BaseCard class="detail-panel">
        <div class="title-row"><h2>Backend Processes</h2><StatusBadge :value="backendProcessStatus" /></div>
        <div class="table-wrap">
          <table class="data-table process-table">
            <thead><tr><th>Process</th><th>Session</th><th>State</th><th>Last Contact</th></tr></thead>
            <tbody><tr v-for="runtime in runtimes" :key="runtime.runtime_id"><td>Runtime host</td><td>Session {{ runtime.session_id }}</td><td>{{ runtime.state }}</td><td><code>{{ formatCentralTimestamp(runtime.last_seen_at) }}</code></td></tr><tr v-if="!runtimes.length"><td colspan="4">No runtime ownership rows reported.</td></tr></tbody>
          </table>
        </div>
      </BaseCard>
    </section>
    <BaseCard class="workspace-card">
      <TabBar :tabs="tabs" :active="activeTab" @change="activeTab = $event" />
      <div v-if="activeTab === 'session-monitors'" class="table-wrap">
        <table class="data-table">
          <thead><tr><th>Monitor ID</th><th>Session</th><th>Process</th><th>Comms</th><th>Last Report</th><th>Reconciliation</th><th>Diagnostic ID</th></tr></thead>
          <tbody><tr v-for="item in runtimes" :key="item.runtime_id"><td><code>{{ item.runtime_id }}</code></td><td>Session {{ item.session_id }}</td><td>{{ item.state }}</td><td><StatusBadge compact :value="item.state" /></td><td><code>{{ formatCentralTimestamp(item.last_seen_at) }}</code></td><td>{{ item.details?.reconciliation ?? "Unknown" }}</td><td><code>{{ item.watchdog_id ?? "—" }}</code></td></tr><tr v-if="!runtimes.length"><td colspan="7">No runtime ownership rows reported.</td></tr></tbody>
        </table>
      </div>
      <div v-else-if="activeTab === 'streams'" class="table-wrap">
        <table class="data-table">
          <thead><tr><th>Session</th><th>Stream</th><th>Device</th><th>Owner</th><th>Desired</th><th>Actual</th><th>Stream Status</th><th>Last Data</th></tr></thead>
          <tbody><tr><td colspan="8">Stream-level health is not exposed by the runtime ownership endpoint.</td></tr></tbody>
        </table>
      </div>
      <div v-else class="storage-grid">
        <BaseCard><h3>Storage</h3><p>Storage metadata is not exposed by the current health contract.</p></BaseCard>
        <BaseCard><h3>Permanent Records</h3><p>Record counts are unavailable from the current health contract.</p></BaseCard>
        <BaseCard class="storage-destinations"><h3>Output Destinations</h3><p>Path access and free-space evidence is unavailable.</p></BaseCard>
      </div>
    </BaseCard>
    <p v-if="healthState === 'degraded' || healthState === 'unavailable'" class="detail-alert">Some system-health sources are unavailable: {{ healthError }}</p>
    <p v-if="actionError" class="detail-alert">{{ actionError }}</p>
    <GuardedDialog v-if="action === 'reconcile'" title="Reconcile Runtime Ownership" description="This refreshes ownership evidence and may release only runtimes proven to be stopped." confirm-label="Reconcile" @close="action = null" @confirm="() => runAction(reconcileRuntimes)" />
    <GuardedDialog v-if="action === 'restart'" title="Restart Control Plane" description="The control plane will quiesce lifecycle commands and schedule its own restart. Runtime hosts are preserved." confirm-label="Restart Control Plane" danger @close="action = null" @confirm="() => runAction(restartControlPlane)" />
    <GuardedDialog v-if="action === 'shutdown'" title="Shutdown Control Plane" description="This schedules control-plane shutdown and runtime shutdown. Force runtime shutdown is enabled only when explicitly selected." confirm-label="Shutdown" danger @close="action = null" @confirm="() => runAction(() => shutdownControlPlane(cascade))" />
  </div>
</template>
