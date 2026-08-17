<script setup>
import { computed, ref, watch } from "vue";
import { Filter, RefreshCw, Search } from "@lucide/vue";
import BaseButton from "../components/BaseButton.vue";
import BaseCard from "../components/BaseCard.vue";
import ErrorNotification from "../components/ErrorNotification.vue";
import PageHeader from "../components/PageHeader.vue";
import StatusBadge from "../components/StatusBadge.vue";
import TabBar from "../components/TabBar.vue";
import { countSessionsForTab, filterSessions, sessionTabs } from "../session-utils";
import { formatCentralDate, formatCentralTimestamp } from "../datetime";

const props = defineProps({
  sessions: { type: Array, required: true },
  catalogState: { type: String, default: "live" },
  loadError: { type: String, default: "" },
});

defineEmits(["open-session", "open-templates", "retry"]);

const activeTab = ref("all");
const search = ref("");
// STOPPED was the old intermediate state between stopping a run and explicitly
// completing it. A stopped run is now terminal, so keep older catalog payloads
// readable without exposing the retired lifecycle in the UI.
const sessions = computed(() => props.sessions.map((session) =>
  String(session.lifecycle).toLowerCase() === "stopped"
    ? { ...session, lifecycle: "Completed" }
    : session,
));
const visibleSessions = computed(() => filterSessions(sessions.value, activeTab.value, search.value));
const counts = computed(() => Object.fromEntries(
  sessionTabs.map((tab) => [tab.id, countSessionsForTab(sessions.value, tab.id)]),
));
const dismissedSessionError = ref("");
const sessionErrorMessage = computed(() => {
  const detail = props.loadError.trim();
  let summary = "";
  if (props.catalogState === "unavailable") summary = "Backend unavailable. No sessions are available.";
  if (props.catalogState === "degraded") summary = "Partial data: session overview is unavailable.";
  return summary && detail ? `${summary} ${detail}` : summary;
});
const showSessionError = computed(
  () => sessionErrorMessage.value && sessionErrorMessage.value !== dismissedSessionError.value,
);

watch(sessionErrorMessage, (message, previousMessage) => {
  if (message !== previousMessage) dismissedSessionError.value = "";
});

function timeLabel(session) {
  if (session.lifecycle === "Active") return session.duration ?? "In progress";
  if (session.scheduledTime) {
    return formatCentralTimestamp(session.scheduledTime, {
      year: undefined,
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: undefined,
    });
  }
  if (session.startTime) return formatCentralDate(session.startTime, { year: undefined });
  return "-";
}
</script>

<template>
  <div class="page page--workspace">
    <PageHeader
      eyebrow="Session workspace"
      title="Sessions"
      description="Review acquisition runs, then return to a reusable template when you need another."
    >
      <BaseButton @click="$emit('open-templates')">Browse Templates</BaseButton>
    </PageHeader>

    <BaseCard class="workspace-card">
      <div v-if="catalogState === 'loading'" class="detail-alert" aria-live="polite">
        <RefreshCw :size="17" class="spin" /> Loading sessions from the backend…
      </div>
      <div class="workspace-chrome">
        <TabBar :tabs="sessionTabs" :active="activeTab" :counts="counts" @change="activeTab = $event" />
        <div class="toolbar">
          <label class="search-field">
            <Search :size="17" />
            <input v-model="search" type="search" placeholder="Search sessions or experiments..." />
          </label>
          <BaseButton variant="secondary"><Filter :size="16" /> Filter</BaseButton>
        </div>
      </div>

      <div v-if="visibleSessions.length" class="table-wrap">
        <table class="data-table sessions-table">
          <thead>
            <tr><th>Session</th><th>State</th><th>Session Health</th><th>Experiment</th><th>Streams</th><th>Time</th><th /></tr>
          </thead>
          <tbody>
            <tr v-for="session in visibleSessions" :key="session.id" @click="$emit('open-session', session.id)">
              <td>
                <strong>{{ session.name }}</strong>
                <small v-if="session.attentionReason">{{ session.attentionReason }}</small>
              </td>
              <td><StatusBadge :value="session.lifecycle" /></td>
              <td><StatusBadge :value="session.health" /></td>
              <td>{{ session.experiment ?? "-" }}</td>
              <td><code>{{ session.streamCount ?? session.deviceCount }}/{{ session.sinkCount }}</code></td>
              <td><code>{{ timeLabel(session) }}</code></td>
              <td><button class="table-action" type="button" @click.stop="$emit('open-session', session.id)">Open</button></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-state">
        <h3>No sessions in this category</h3>
        <p>Try another tab or change the current search.</p>
      </div>
    </BaseCard>

    <ErrorNotification
      v-if="showSessionError"
      :message="sessionErrorMessage"
      @dismiss="dismissedSessionError = sessionErrorMessage"
    >
      <button type="button" @click="$emit('retry')"><RefreshCw :size="15" /> Retry</button>
    </ErrorNotification>
  </div>
</template>
