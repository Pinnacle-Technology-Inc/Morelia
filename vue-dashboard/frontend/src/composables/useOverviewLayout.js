import { computed, ref, toValue, watch } from "vue";
import {
  getSessionDeviceFlows,
  getVisibleActiveSessions,
  loadOverviewPreferences,
  moveSessionByOffset,
  reconcileActiveSessionOrder,
  reorderSessionIds,
  saveOverviewPreferences,
} from "../overview-utils";

const OVERVIEW_STORAGE_KEY = "guarded-overview-preferences-v1";
export const DEFAULT_VISIBLE_ACTIVE_SESSIONS = 4;

export function useOverviewLayout(activeSessions, deviceFlows, storage) {
  const savedPreferences = loadOverviewPreferences(storage, OVERVIEW_STORAGE_KEY);
  const activeSessionById = computed(() => new Map(
    toValue(activeSessions).map((session) => [session.id, session]),
  ));
  const orderedActiveSessionIds = ref(
    reconcileActiveSessionOrder(toValue(activeSessions), savedPreferences.orderedSessionIds),
  );
  const expandedSessionIds = ref(
    savedPreferences.expandedSessionIds.filter((id) => activeSessionById.value.has(id)),
  );
  const showAllActiveSessions = ref(savedPreferences.showAllActiveSessions);
  const isSidebarCollapsed = ref(savedPreferences.isSidebarCollapsed);
  const collapsedSidebarSections = ref(savedPreferences.collapsedSidebarSections);
  const draggedSessionId = ref(null);
  const dropTarget = ref(null);
  const reorderAnnouncement = ref("");

  const orderedActiveSessions = computed(() =>
    orderedActiveSessionIds.value
      .map((id) => activeSessionById.value.get(id))
      .filter(Boolean),
  );
  const visibleActiveSessions = computed(() =>
    getVisibleActiveSessions(
      orderedActiveSessions.value,
      showAllActiveSessions.value,
      DEFAULT_VISIBLE_ACTIVE_SESSIONS,
    ),
  );

  watch(
    [
      orderedActiveSessionIds,
      expandedSessionIds,
      showAllActiveSessions,
      isSidebarCollapsed,
      collapsedSidebarSections,
    ],
    () => {
      saveOverviewPreferences(storage, OVERVIEW_STORAGE_KEY, {
        orderedSessionIds: orderedActiveSessionIds.value,
        expandedSessionIds: expandedSessionIds.value,
        showAllActiveSessions: showAllActiveSessions.value,
        isSidebarCollapsed: isSidebarCollapsed.value,
        collapsedSidebarSections: collapsedSidebarSections.value,
      });
    },
    { deep: true },
  );

  watch(activeSessions, (sessions) => {
    const nextIds = reconcileActiveSessionOrder(toValue(activeSessions), orderedActiveSessionIds.value);
    orderedActiveSessionIds.value = nextIds;
    expandedSessionIds.value = expandedSessionIds.value.filter((id) => activeSessionById.value.has(id));
  });

  function isSessionExpanded(sessionId) {
    return expandedSessionIds.value.includes(sessionId);
  }

  function toggleSession(sessionId) {
    expandedSessionIds.value = isSessionExpanded(sessionId)
      ? expandedSessionIds.value.filter((id) => id !== sessionId)
      : [...expandedSessionIds.value, sessionId];
  }

  function devicesForSession(sessionId) {
    return getSessionDeviceFlows(toValue(deviceFlows), sessionId);
  }

  function startSessionDrag(sessionId, event) {
    draggedSessionId.value = sessionId;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", sessionId);
  }

  function setDropTarget(sessionId, event) {
    if (!draggedSessionId.value || draggedSessionId.value === sessionId) {
      dropTarget.value = null;
      return;
    }

    const bounds = event.currentTarget.getBoundingClientRect();
    const position = event.clientX < bounds.left + bounds.width / 2 ? "before" : "after";
    event.dataTransfer.dropEffect = "move";
    dropTarget.value = { sessionId, position };
  }

  function endSessionDrag() {
    draggedSessionId.value = null;
    dropTarget.value = null;
  }

  function dropSession(sessionId) {
    if (!draggedSessionId.value || !dropTarget.value) return;

    orderedActiveSessionIds.value = reorderSessionIds(
      orderedActiveSessionIds.value,
      draggedSessionId.value,
      sessionId,
      dropTarget.value.position,
    );
    const movedSession = activeSessionById.value.get(draggedSessionId.value);
    reorderAnnouncement.value = `${movedSession?.name ?? "Session"} reordered.`;
    endSessionDrag();
  }

  function moveSession(sessionId, offset) {
    const nextOrder = moveSessionByOffset(orderedActiveSessionIds.value, sessionId, offset);
    if (nextOrder.join() === orderedActiveSessionIds.value.join()) return;

    orderedActiveSessionIds.value = nextOrder;
    const movedSession = activeSessionById.value.get(sessionId);
    reorderAnnouncement.value = `${movedSession?.name ?? "Session"} moved ${
      offset < 0 ? "earlier" : "later"
    }.`;
  }

  function setSidebarCollapsed(value) {
    isSidebarCollapsed.value = value;
  }

  function setCollapsedSidebarSections(value) {
    collapsedSidebarSections.value = value;
  }

  return {
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
  };
}
