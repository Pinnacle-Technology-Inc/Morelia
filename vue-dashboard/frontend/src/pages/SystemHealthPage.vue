<script setup>
import { ref } from "vue";
import { Power, ShieldAlert } from "@lucide/vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import PageHeader from "../components/PageHeader.vue";
import StatusBadge from "../components/StatusBadge.vue";
import TabBar from "../components/TabBar.vue";

const activeTab = ref("session-monitors");
const tabs = [
  { id: "session-monitors", label: "Session Monitors" },
  { id: "streams", label: "Streams" },
  { id: "storage", label: "Storage" },
];

const sessionMonitors = [
  { id: "mon-3c8d", session: "Cortical Array #07", process: "Running", comms: "Current", report: "08:48:31", restarts: 0, reconciliation: "Reconciled", diagnosticId: "wdg-3c8d" },
  { id: "mon-1b2c", session: "Cortical Array #07", process: "Running", comms: "Current", report: "08:48:31", restarts: 0, reconciliation: "Reconciled", diagnosticId: "wdg-1b2c" },
  { id: "mon-9f2a", session: "Striatal LFP", process: "Stopped", comms: "Stopped", report: "08:42:11", restarts: 1, reconciliation: "Needs action", diagnosticId: "wdg-9f2a" },
];

const backendProcesses = [
  { kind: "Runtime host", session: "Cortical Array Session 07", state: "Alive", contact: "0s ago" },
  { kind: "Watchdog", session: "Cortical Array Session 07", state: "Alive", contact: "0s ago" },
  { kind: "Runtime host", session: "Striatal LFP Recording", state: "Not alive", contact: "6m ago" },
];
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
        <div class="title-row"><h2>Daemon</h2><StatusBadge value="Running" /></div>
        <dl class="detail-list">
          <div><dt>Status</dt><dd>Running · PID 4182 · http://127.0.0.1:8080</dd></div>
          <div><dt>Doctor</dt><dd>Database, runtime directory, and command channel checks passed</dd></div>
        </dl>
        <div class="daemon-actions">
          <BaseButton variant="danger"><Power :size="16" /> Shutdown</BaseButton>
          <label class="cascade-option"><input type="checkbox" /> Cascade</label>
          <BaseButton variant="secondary"><ShieldAlert :size="16" /> Force Stop Session</BaseButton>
        </div>
        <p class="helper-copy">Runtime agents self-terminate after about 30 minutes without daemon contact.</p>
      </BaseCard>
      <BaseCard class="detail-panel">
        <div class="title-row"><h2>Backend Processes</h2><StatusBadge value="Attention" /></div>
        <div class="table-wrap">
          <table class="data-table process-table">
            <thead><tr><th>Process</th><th>Session</th><th>State</th><th>Last Contact</th></tr></thead>
            <tbody><tr v-for="process in backendProcesses" :key="`${process.kind}-${process.session}`"><td>{{ process.kind }}</td><td>{{ process.session }}</td><td>{{ process.state }}</td><td><code>{{ process.contact }}</code></td></tr></tbody>
          </table>
        </div>
      </BaseCard>
    </section>
    <BaseCard class="workspace-card">
      <TabBar :tabs="tabs" :active="activeTab" @change="activeTab = $event" />
      <div v-if="activeTab === 'session-monitors'" class="table-wrap">
        <table class="data-table">
          <thead><tr><th>Monitor ID</th><th>Session</th><th>Process</th><th>Comms</th><th>Last Report</th><th>Reconciliation</th><th>Diagnostic ID</th></tr></thead>
          <tbody><tr v-for="item in sessionMonitors" :key="item.id"><td><code>{{ item.id }}</code></td><td>{{ item.session }}</td><td>{{ item.process }}</td><td><StatusBadge compact :value="item.comms" /></td><td><code>{{ item.report }}</code></td><td>{{ item.reconciliation }}</td><td><code>{{ item.diagnosticId }}</code></td></tr></tbody>
        </table>
      </div>
      <div v-else-if="activeTab === 'streams'" class="table-wrap">
        <table class="data-table">
          <thead><tr><th>Session</th><th>Stream</th><th>Device</th><th>Owner</th><th>Desired</th><th>Actual</th><th>Stream Status</th><th>Last Data</th></tr></thead>
          <tbody>
            <tr><td>Cortical Array #07</td><td>M32-007</td><td><code>M32-007-HW</code></td><td>Owner session</td><td>Active</td><td>Active</td><td><StatusBadge value="Healthy" /></td><td>0s ago</td></tr>
            <tr><td>Striatal LFP</td><td>M16-003</td><td><code>M16-003-HW</code></td><td>Owner session</td><td>Active</td><td>Stopped</td><td><StatusBadge value="Unhealthy" /></td><td>6m ago</td></tr>
          </tbody>
        </table>
      </div>
      <div v-else class="storage-grid">
        <BaseCard><h3>Database</h3><dl class="detail-list"><div><dt>State</dt><dd>Healthy</dd></div><div><dt>Location</dt><dd>/var/lib/guarded/experiment.db</dd></div><div><dt>Size</dt><dd>142 MB</dd></div></dl></BaseCard>
        <BaseCard><h3>Permanent Records</h3><dl class="detail-list"><div><dt>Incidents</dt><dd>47</dd></div><div><dt>Data gaps</dt><dd>12</dd></div><div><dt>Recovery records</dt><dd>38</dd></div><div><dt>Session notes</dt><dd>104</dd></div></dl></BaseCard>
        <BaseCard class="storage-destinations"><h3>Output Destinations</h3><div class="table-wrap"><table class="data-table"><thead><tr><th>Path</th><th>Accessible</th><th>Writable</th><th>Free Space</th></tr></thead><tbody><tr><td><code>/data/cortical</code></td><td>Yes</td><td>Yes</td><td>4.2 GB</td></tr><tr><td><code>/data/striatal</code></td><td>Yes</td><td>Yes</td><td>8.7 GB</td></tr></tbody></table></div></BaseCard>
      </div>
    </BaseCard>
  </div>
</template>
