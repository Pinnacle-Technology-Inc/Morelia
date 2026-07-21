<script setup>
import { ref } from "vue";
import BaseCard from "../components/BaseCard.vue";
import PageHeader from "../components/PageHeader.vue";
import StatusBadge from "../components/StatusBadge.vue";
import TabBar from "../components/TabBar.vue";
import { incidents } from "../data";

const activeTab = ref("incidents");
const tabs = [
  { id: "incidents", label: "Incidents" },
  { id: "gaps", label: "Data Gaps" },
  { id: "history", label: "Recovery History" },
];
</script>

<template>
  <div class="page page--workspace">
    <PageHeader
      eyebrow="Permanent operational record"
      title="Incidents & Gaps"
      description="Review interruptions, data gaps, guarded actions, and verification outcomes."
    />
    <BaseCard class="workspace-card">
      <TabBar :tabs="tabs" :active="activeTab" @change="activeTab = $event" />
      <div class="table-wrap">
        <table v-if="activeTab === 'incidents'" class="data-table">
          <thead><tr><th>Time</th><th>Session</th><th>Stream</th><th>Reason</th><th>Policy</th><th>Outcome</th><th>State</th><th /></tr></thead>
          <tbody>
            <tr v-for="incident in incidents" :key="incident.id">
              <td><code>{{ incident.time }}</code></td><td><strong>{{ incident.sessionName }}</strong></td>
              <td><code>{{ incident.stream }}</code></td><td>{{ incident.reason }}</td><td>Recommend</td>
              <td><StatusBadge compact :value="incident.outcome" /></td>
              <td>{{ incident.resolved ? "Resolved" : "Open" }}</td>
              <td><div class="row-actions"><button class="table-action" type="button">Open</button><button v-if="!incident.resolved" class="table-action" type="button">Acknowledge</button></div></td>
            </tr>
          </tbody>
        </table>
        <table v-else-if="activeTab === 'gaps'" class="data-table">
          <thead><tr><th>Start</th><th>End</th><th>Duration</th><th>Session</th><th>Stream</th><th>Cause</th><th>Incident</th><th>Outcome</th><th /></tr></thead>
          <tbody><tr><td><code>07:10:04</code></td><td><code>07:10:08</code></td><td>4 s</td><td>Cortical Array Session 07</td><td>M32-007</td><td>NFS mount stall</td><td>INC-i002</td><td>Recovered</td><td><button class="table-action" type="button">Add Note</button></td></tr></tbody>
        </table>
        <table v-else class="data-table">
          <thead><tr><th>Time</th><th>Session</th><th>Stream</th><th>Phase</th><th>Action</th><th>Verification</th><th>Outcome</th><th>Policy</th></tr></thead>
          <tbody><tr><td><code>07:11</code></td><td>Cortical Array Session 07</td><td>M32-007</td><td>Verify</td><td>Reconnect</td><td>3/3 passed</td><td>Recovered</td><td>Recommend</td></tr></tbody>
        </table>
      </div>
    </BaseCard>
  </div>
</template>
