<script setup>
import { onMounted, ref, watch } from "vue";
import BaseCard from "../components/BaseCard.vue";
import PageHeader from "../components/PageHeader.vue";
import StatusBadge from "../components/StatusBadge.vue";
import TabBar from "../components/TabBar.vue";
import { acknowledgeIncident, loadGaps, loadIncidents } from "../history-api";

const activeTab = ref("incidents");
const rows = ref([]);
const pageState = ref("loading");
const pageError = ref("");
const nextCursor = ref(null);
const hasMore = ref(false);
const status = ref("");
const confidence = ref("");
const pageSize = 50;
const tabs = [
  { id: "incidents", label: "Incidents" },
  { id: "gaps", label: "Data Gaps" },
  { id: "history", label: "Recovery History" },
];

function formatGapBoundary(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string" || typeof value === "number") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return "Unavailable";
  }
}

function gapBoundaryTime(value) {
  const timestamp = value && typeof value === "object" ? value.ts : value;
  if (typeof timestamp !== "string" && typeof timestamp !== "number") return null;
  const parsed = new Date(timestamp).getTime();
  return Number.isNaN(parsed) ? null : parsed;
}

function formatGapDuration(gap) {
  // Boundaries can also be sample/row evidence, where subtraction would invent
  // a time unit. Only calculate a duration when the API gave two timestamps.
  const start = gapBoundaryTime(gap.gap_start);
  const end = gapBoundaryTime(gap.gap_end);
  if (start === null || end === null || end < start) return "—";
  const durationMs = end - start;
  const seconds = Math.floor(durationMs / 1000);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = seconds % 60;
  return hours ? `${hours}h ${minutes}m ${remainingSeconds}s` : `${minutes}m ${remainingSeconds}s`;
}

function incidentOutcome(incident) {
  if (incident.resolution) return incident.resolution;
  return incident.status === "resolved" ? "Unavailable" : "Pending";
}

async function loadPage(cursor = null) {
  if (activeTab.value === "history") return;
  pageState.value = "loading";
  pageError.value = "";
  try {
    const page = activeTab.value === "incidents"
      ? await loadIncidents({ status: status.value || undefined, pageSize, cursor })
      : await loadGaps({ confidence: confidence.value || undefined, pageSize, cursor });
    rows.value = Array.isArray(page.items) ? page.items : [];
    nextCursor.value = page.next_cursor ?? null;
    hasMore.value = page.has_more === true;
    pageState.value = "live";
  } catch (error) {
    rows.value = [];
    nextCursor.value = null;
    hasMore.value = false;
    pageState.value = "unavailable";
    pageError.value = error instanceof Error ? error.message : "History is unavailable.";
  }
}

async function acknowledge(incident) {
  const note = window.prompt("Acknowledgement note (optional):", "");
  if (note === null) return;
  await acknowledgeIncident(incident.incident_id, { acknowledgedBy: "operator", note });
  await loadPage();
}

watch(activeTab, () => loadPage());
watch([status, confidence], () => loadPage());
onMounted(() => loadPage());
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
      <div v-if="activeTab !== 'history'" class="detail-tab-actions">
        <label>Filter <select v-if="activeTab === 'incidents'" v-model="status"><option value="">All states</option><option value="open">Open</option><option value="acknowledged">Acknowledged</option><option value="resolved">Resolved</option></select><select v-else v-model="confidence"><option value="">All confidence</option><option value="confirmed">Confirmed</option><option value="estimated">Estimated</option><option value="uncertain">Uncertain</option></select></label>
      </div>
      <p v-if="pageState === 'loading'">Loading history…</p>
      <p v-else-if="pageState === 'unavailable'" class="detail-alert">{{ pageError }}</p>
      <p v-else-if="activeTab === 'history'" class="detail-alert">Recovery history is unavailable: no backend contract is defined yet.</p>
      <div class="table-wrap">
        <table v-if="activeTab === 'incidents'" class="data-table">
          <thead><tr><th>Time</th><th>Session</th><th>Stream</th><th>Reason</th><th>Policy</th><th>Outcome</th><th>State</th><th /></tr></thead>
          <tbody>
            <tr v-for="incident in rows" :key="incident.incident_id">
              <td><code>{{ incident.opened_at ?? "—" }}</code></td><td><strong>Session {{ incident.session_id }}</strong></td>
              <td><code>{{ incident.device_id ?? "—" }}</code></td><td>{{ incident.reason }}</td><td>{{ incident.policy ?? "—" }}</td>
              <td>{{ incidentOutcome(incident) }}</td><td><StatusBadge compact :value="incident.status" /></td>
              <td><button v-if="incident.status === 'open'" class="table-action" type="button" @click="acknowledge(incident)">Acknowledge</button></td>
            </tr>
          </tbody>
        </table>
        <table v-else-if="activeTab === 'gaps'" class="data-table">
          <thead><tr><th>Start</th><th>End</th><th>Duration</th><th>Session</th><th>Stream</th><th>Cause</th><th>Incident</th><th>Confidence</th></tr></thead>
          <tbody><tr v-for="gap in rows" :key="gap.gap_id"><td><code>{{ formatGapBoundary(gap.gap_start) }}</code></td><td><code>{{ formatGapBoundary(gap.gap_end) }}</code></td><td>{{ formatGapDuration(gap) }}</td><td><strong>Session {{ gap.session_id }}</strong></td><td><code>{{ gap.sink_id ?? gap.device_id ?? "—" }}</code></td><td>{{ gap.reason ?? "—" }}</td><td><code>{{ gap.incident_id ?? "—" }}</code></td><td>{{ gap.confidence ?? "—" }}</td></tr></tbody>
        </table>
        <div v-if="activeTab !== 'history' && pageState === 'live' && hasMore"><button type="button" class="table-action" @click="loadPage(nextCursor)">Next page</button></div>
      </div>
    </BaseCard>
  </div>
</template>
