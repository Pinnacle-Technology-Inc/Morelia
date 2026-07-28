<script setup>
import { computed } from "vue";
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

const props = defineProps({
  sessions: { type: Array, required: true },
  catalogState: { type: String, default: "live" },
  loadError: { type: String, default: "" },
});

defineEmits(["open-session", "view-attention", "create-session"]);

const attention = computed(() => summarizeAttentionSessions(props.sessions));
const activeSessions = computed(() => props.sessions.filter((session) => session.lifecycle === "Active"));
const scheduled = computed(() => props.sessions.filter((session) => session.lifecycle === "Scheduled"));
const deviceFlows = computed(() => props.sessions.flatMap((session) =>
  (Array.isArray(session.deviceFlows) ? session.deviceFlows : []).map((flow) => ({
    ...flow,
    sessionId: session.id,
  })),
));
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
            <p>Ready when you are — create a new session to start collecting.</p>
          
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
      <SectionTitle title="Recent Incidents & Recoveries" />
      <BaseCard><div class="empty-state">Recent incidents and recoveries are unavailable until the live history contract is wired.</div></BaseCard>
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
</style>
