<script setup>
import { ChevronDown } from "@lucide/vue";
import ActiveSessionCard from "../components/ActiveSessionCard.vue";
import BaseCard from "../components/BaseCard.vue";
import OverviewSidebar from "../components/OverviewSidebar.vue";
import OverviewSidebarSplitter from "../components/OverviewSidebarSplitter.vue";
import SectionTitle from "../components/SectionTitle.vue";
import StatusBadge from "../components/StatusBadge.vue";
import { deviceFlows, incidents, sessions } from "../data";
import {
  DEFAULT_VISIBLE_ACTIVE_SESSIONS,
  useOverviewLayout,
} from "../composables/useOverviewLayout";
import { summarizeAttentionSessions } from "../session-utils";

defineEmits(["open-session", "view-attention"]);

const attention = summarizeAttentionSessions(sessions);
const activeSessions = sessions.filter((session) => session.lifecycle === "Active");
const scheduled = sessions.filter((session) => session.lifecycle === "Scheduled");
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
          <div class="session-card-grid">
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
      <BaseCard>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Time</th><th>Session</th><th>Stream</th><th>Reason</th><th>Outcome</th></tr></thead>
            <tbody>
              <tr v-for="incident in incidents" :key="incident.id">
                <td><code>{{ incident.time }}</code></td>
                <td><button class="table-action" type="button" @click="$emit('open-session', incident.sessionId)">{{ incident.sessionName }}</button></td>
                <td><code>{{ incident.stream }}</code></td>
                <td>{{ incident.reason }}</td>
                <td><StatusBadge compact :value="incident.outcome" /></td>
              </tr>
            </tbody>
          </table>
        </div>
      </BaseCard>
    </section>
  </div>
</template>
