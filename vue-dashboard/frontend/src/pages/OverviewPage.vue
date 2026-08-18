<script setup>
import { computed, onMounted, ref } from "vue";
import { ChevronDown } from "@lucide/vue";
import ActiveSessionCard from "../components/ActiveSessionCard.vue";
import BaseCard from "../components/BaseCard.vue";
import OverviewSidebar from "../components/OverviewSidebar.vue";
import OverviewSidebarSplitter from "../components/OverviewSidebarSplitter.vue";
import SectionTitle from "../components/SectionTitle.vue";
import emptySessionsArt from "../assets/overview-empty-mouse.png";
import {
  DEFAULT_VISIBLE_ACTIVE_SESSIONS,
  useOverviewLayout,
} from "../composables/useOverviewLayout";
import { summarizeAttentionSessions } from "../session-utils";
import { loadDeviceConfigs } from "../devices-api";
import { formatCentralTimestamp } from "../datetime";
import { loadIncidents } from "../history-api";

const RECENT_INCIDENT_LIMIT = 5;

const props = defineProps({
  sessions: { type: Array, required: true },
  catalogState: { type: String, default: "live" },
  loadError: { type: String, default: "" },
});

defineEmits(["open-session", "view-attention", "view-history", "create-session"]);

const attention = computed(() => summarizeAttentionSessions(props.sessions));
const activeSessions = computed(() => props.sessions.filter((session) => session.lifecycle === "Active"));
const scheduled = computed(() => props.sessions.filter((session) => session.lifecycle === "Scheduled"));
const deviceConfigs = ref([]);
const recentIncidents = ref([]);
const recentHistoryState = ref("loading");
const recentHistoryError = ref("");
const deviceFlows = computed(() => props.sessions.flatMap((session) =>
  (Array.isArray(session.deviceFlows) ? session.deviceFlows : []).map((flow) => ({
    ...flow,
    sessionId: session.id,
  })),
));

onMounted(async () => {
  try {
    deviceConfigs.value = await loadDeviceConfigs();
  } catch {
    deviceConfigs.value = [];
  }
});

onMounted(async () => {
  try {
    const page = await loadIncidents({ pageSize: RECENT_INCIDENT_LIMIT });
    recentIncidents.value = Array.isArray(page.items) ? page.items : [];
    recentHistoryState.value = "live";
  } catch (error) {
    recentIncidents.value = [];
    recentHistoryState.value = "unavailable";
    recentHistoryError.value = error instanceof Error
      ? error.message
      : "Recent incident history is unavailable.";
  }
});

function incidentStream(incident) {
  return incident.sink_id ?? incident.device_id ?? incident.dataflow_id ?? "—";
}

function incidentOutcome(incident) {
  if (incident.resolution) return incident.resolution;
  return incident.status === "resolved" ? "Unavailable" : "Pending";
}

let storage = null;
try {
  storage = window.localStorage;
} catch {
  storage = null;
}

const {
  collapsedSidebarSections,
  devicesForSession,
  draggedSessionId,
  dropSession,
  dropTarget,
  endSessionDrag,
  isSessionExpanded,
  isSidebarCollapsed,
  moveSession,
  orderedActiveSessions,
  reorderAnnouncement,
  setCollapsedSidebarSections,
  setDropTarget,
  setSidebarCollapsed,
  showAllActiveSessions,
  startSessionDrag,
  toggleSession,
  visibleActiveSessions,
} = useOverviewLayout(activeSessions, deviceFlows, storage);
</script>

<template>
  <div class="page page--overview">
    <div v-if="catalogState === 'unavailable'" class="detail-alert" role="alert">
      <span>Backend unavailable. No live sessions are available. {{ loadError }}</span>
      <button type="button" @click="$emit('view-attention')">Open Sessions</button>
    </div>
    <div v-else-if="catalogState === 'degraded'" class="detail-alert" role="alert">
      <span>Partial session data: overview details are unavailable. {{ loadError }}</span>
    </div>

    <div
      class="overview-columns"
      :class="{ 'overview-columns--side-collapsed': isSidebarCollapsed }"
    >
      <div class="overview-main">

        <section>
          <SectionTitle :title="`Active Sessions (${orderedActiveSessions.length})`" />
          <p id="session-sort-instructions" class="visually-hidden">
            Drag a session by its handle or use the arrow keys while the handle is focused.
          </p>
          <p class="visually-hidden" aria-live="polite">{{ reorderAnnouncement }}</p>
          <div v-if="catalogState === 'loading'" class="empty-state">Loading live sessions…</div>
          <div v-else-if="catalogState === 'unavailable'" class="empty-state empty-state--welcome">
            <img
              class="empty-state__art"
              :src="emptySessionsArt"
              alt=""
              width="220"
              height="220"
            />
            <h3>No live sessions right now</h3>
            <p>The backend is unreachable, so session cards cannot load yet.</p>
            <button type="button" class="button button--secondary" @click="$emit('view-attention')">
              Open Sessions
            </button>
          </div>
          <div v-else-if="!orderedActiveSessions.length" class="empty-state empty-state--welcome">
            <img
              class="empty-state__art"
              :src="emptySessionsArt"
              alt=""
              width="220"
              height="220"
            />
            <h3>No sessions are active</h3>
            <p>Ready when you are — Spin up a session from an existing template</p>
          
          </div>
          <div v-else class="session-card-grid">
            <div
              v-for="session in visibleActiveSessions"
              :key="session.id"
              class="session-card-slot"
              :class="{
                'session-card-slot--dragging': draggedSessionId === session.id,
                'session-card-slot--drop-before':
                  dropTarget?.sessionId === session.id && dropTarget.position === 'before',
                'session-card-slot--drop-after':
                  dropTarget?.sessionId === session.id && dropTarget.position === 'after',
              }"
              @dragover.prevent="setDropTarget(session.id, $event)"
              @drop.prevent="dropSession(session.id)"
            >
              <ActiveSessionCard
                :session="session"
                :devices="devicesForSession(session.id)"
                :device-configs="deviceConfigs"
                :expanded="isSessionExpanded(session.id)"
                @drag-start="startSessionDrag"
                @drag-end="endSessionDrag"
                @move="moveSession"
                @open="$emit('open-session', $event)"
                @toggle="toggleSession"
              />
            </div>
          </div>
          <button
            v-if="orderedActiveSessions.length > DEFAULT_VISIBLE_ACTIVE_SESSIONS"
            class="active-sessions-toggle"
            type="button"
            :aria-expanded="showAllActiveSessions"
            @click="showAllActiveSessions = !showAllActiveSessions"
          >
            {{
              showAllActiveSessions
                ? `Show top ${DEFAULT_VISIBLE_ACTIVE_SESSIONS} sessions`
                : `Show all ${orderedActiveSessions.length} active sessions`
            }}
            <ChevronDown
              :size="16"
              :class="{ 'active-sessions-toggle__icon--expanded': showAllActiveSessions }"
            />
          </button>
        </section>
      </div>

      <OverviewSidebarSplitter
        :collapsed="isSidebarCollapsed"
        @update:collapsed="setSidebarCollapsed"
      />

      <OverviewSidebar
        :attention="attention"
        :scheduled="scheduled"
        :collapsed="isSidebarCollapsed"
        :collapsed-sections="collapsedSidebarSections"
        @open-session="$emit('open-session', $event)"
        @update:collapsed="setSidebarCollapsed"
        @update:collapsed-sections="setCollapsedSidebarSections"
        @view-attention="$emit('view-attention')"
      />
    </div>

    <section>
      <SectionTitle title="Recent Incidents & Recoveries">
        <button class="section-link" type="button" @click="$emit('view-history')">
          View history →
        </button>
      </SectionTitle>
      <BaseCard>
        <div
          v-if="recentHistoryState === 'loading'"
          class="empty-state"
          role="status"
        >
          Loading recent incidents…
        </div>
        <div
          v-else-if="recentHistoryState === 'unavailable'"
          class="empty-state"
          role="alert"
        >
          Recent incidents and recoveries are unavailable. {{ recentHistoryError }}
        </div>
        <div v-else-if="!recentIncidents.length" class="empty-state" role="status">
          No incidents or recoveries have been recorded.
        </div>
        <div v-else class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Session</th>
                <th>Stream</th>
                <th>Reason</th>
                <th>Outcome</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="incident in recentIncidents"
                :key="incident.incident_id"
                class="overview-history-row"
                @click="$emit('open-session', String(incident.session_id))"
              >
                <td><code>{{ formatCentralTimestamp(incident.opened_at) }}</code></td>
                <td>
                  <button
                    class="overview-history-link"
                    type="button"
                    @click.stop="$emit('open-session', String(incident.session_id))"
                  >
                    Session {{ incident.session_id }}
                  </button>
                </td>
                <td><code>{{ incidentStream(incident) }}</code></td>
                <td>{{ incident.reason }}</td>
                <td>{{ incidentOutcome(incident) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </BaseCard>
    </section>
  </div>
</template>

<style scoped>
.empty-state--welcome {
  gap: var(--space-3);
  padding: var(--space-6) var(--space-4);
  border: 1px dashed var(--border-card);
  border-radius: var(--radius-md);
  background:
    radial-gradient(circle at 50% 18%, color-mix(in srgb, var(--sage-50) 88%, transparent), transparent 58%),
    var(--surface-card);
}

.empty-state__art {
  display: block;
  width: min(220px, 56vw);
  height: auto;
  margin-bottom: var(--space-1);
  user-select: none;
  pointer-events: none;
}

.empty-state--welcome h3 {
  margin: 0;
  font-size: var(--fs-lg);
  font-weight: var(--fw-bold);
}

.empty-state--welcome p {
  max-width: 28rem;
  margin: 0;
  line-height: var(--lh-body);
}

.empty-state--welcome .button {
  margin-top: var(--space-2);
}

.overview-history-row {
  cursor: pointer;
}

.overview-history-row:hover {
  background: var(--surface-sage);
}

.overview-history-link {
  padding: 0;
  color: inherit;
  border: 0;
  background: transparent;
  font: inherit;
  font-weight: var(--fw-bold);
  cursor: pointer;
}

.overview-history-link:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}
</style>
