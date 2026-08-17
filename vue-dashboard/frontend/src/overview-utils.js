import { timestampMs } from "./datetime";

export function sortSessionsOldestFirst(sessions) {
  return [...sessions].sort((left, right) => {
    const leftTime = timestampMs(left.startTime) ?? Number.POSITIVE_INFINITY;
    const rightTime = timestampMs(right.startTime) ?? Number.POSITIVE_INFINITY;
    return leftTime - rightTime;
  });
}

export function reconcileActiveSessionOrder(sessions, savedIds = []) {
  const sortedIds = sortSessionsOldestFirst(sessions).map((session) => session.id);
  const activeIds = new Set(sortedIds);
  const retainedIds = savedIds.filter(
    (id, index) => activeIds.has(id) && savedIds.indexOf(id) === index,
  );
  const retainedIdSet = new Set(retainedIds);

  return [...retainedIds, ...sortedIds.filter((id) => !retainedIdSet.has(id))];
}

export function reorderSessionIds(ids, sourceId, targetId, position) {
  if (sourceId === targetId || !ids.includes(sourceId) || !ids.includes(targetId)) return [...ids];

  const reordered = ids.filter((id) => id !== sourceId);
  const targetIndex = reordered.indexOf(targetId);
  const insertionIndex = targetIndex + (position === "after" ? 1 : 0);
  reordered.splice(insertionIndex, 0, sourceId);
  return reordered;
}

export function moveSessionByOffset(ids, sessionId, offset) {
  const currentIndex = ids.indexOf(sessionId);
  const nextIndex = currentIndex + offset;
  if (currentIndex < 0 || nextIndex < 0 || nextIndex >= ids.length) return [...ids];

  const reordered = [...ids];
  [reordered[currentIndex], reordered[nextIndex]] = [reordered[nextIndex], reordered[currentIndex]];
  return reordered;
}

export function getVisibleActiveSessions(sessions, showAll, limit = 4) {
  return showAll ? sessions : sessions.slice(0, limit);
}

export function getSessionDeviceFlows(flows, sessionId) {
  return flows.filter((flow) => flow.sessionId === sessionId);
}

function defaultOverviewPreferences() {
  return {
    orderedSessionIds: [],
    expandedSessionIds: [],
    showAllActiveSessions: false,
    isSidebarCollapsed: false,
    collapsedSidebarSections: [],
  };
}

export function loadOverviewPreferences(storage, key) {
  try {
    const saved = JSON.parse(storage?.getItem(key) ?? "null");
    if (!saved || typeof saved !== "object") return defaultOverviewPreferences();

    return {
      orderedSessionIds: Array.isArray(saved.orderedSessionIds)
        ? saved.orderedSessionIds.filter((id) => typeof id === "string")
        : [],
      expandedSessionIds: Array.isArray(saved.expandedSessionIds)
        ? saved.expandedSessionIds.filter((id) => typeof id === "string")
        : [],
      showAllActiveSessions: saved.showAllActiveSessions === true,
      isSidebarCollapsed: saved.isSidebarCollapsed === true,
      collapsedSidebarSections: Array.isArray(saved.collapsedSidebarSections)
        ? saved.collapsedSidebarSections.filter((section) =>
            ["attention", "scheduled"].includes(section),
          )
        : [],
    };
  } catch {
    return defaultOverviewPreferences();
  }
}

export function saveOverviewPreferences(storage, key, preferences) {
  try {
    storage?.setItem(key, JSON.stringify(preferences));
    return Boolean(storage);
  } catch {
    return false;
  }
}
