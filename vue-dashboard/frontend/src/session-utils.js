export const sessionTabs = [
  { id: "all", label: "All" },
  { id: "needs-attention", label: "Needs Attention" },
  { id: "active", label: "Active" },
  { id: "scheduled", label: "Scheduled" },
  { id: "completed", label: "Completed" },
  { id: "archived", label: "Archived" },
];

// ---------------------------------------------------------------------------
// Session health vocabulary
// ---------------------------------------------------------------------------
//
// Health answers ONE question: "is this session's data moving as intended right
// now?" It is a live property — the backend only produces it from a current
// poller snapshot, and returns null rather than inventing one from a stale
// report (see session_status._health_value). That null arrives in two very
// different situations, and collapsing them is what made the badge misleading:
//
//   1. Nothing is running, so there is nothing to measure. Not a fault.
//   2. Something SHOULD be running and we have lost sight of it. A fault.
//
// Case 1 gets its own resting label; case 2 gets `Not reporting`. Neither is
// called "Unknown" any more, because "Unknown" read as case 2 in every row.
export const SessionHealth = Object.freeze({
  NOT_RUNNING: "Not running",
  HEALTHY: "Healthy",
  RECOVERING: "Recovering",
  DELAYED: "Delayed",
  UNREACHABLE: "Unreachable",
  FAILED: "Failed",
  NOT_STREAMING: "Not streaming",
  NOT_REPORTING: "Not reporting",
  NEEDS_ACTION: "Needs action",
});

// Raw backend HealthState (domain/enums.py) -> operator label, for a session
// the control plane believes is running. `delayed`/`unreachable`/`failed` stay
// distinct instead of collapsing into "Needs action": they call for different
// operator responses, and StatusBadge already renders all three. `stopped` here
// is NOT the lifecycle state — it means the dataflow ended while the plane still
// intends the session to run, which is a real disagreement worth its own label.
const LIVE_HEALTH_LABELS = {
  healthy: SessionHealth.HEALTHY,
  suspect: SessionHealth.HEALTHY,
  recovering: SessionHealth.RECOVERING,
  delayed: SessionHealth.DELAYED,
  unreachable: SessionHealth.UNREACHABLE,
  failed: SessionHealth.FAILED,
  stopped: SessionHealth.NOT_STREAMING,
  needs_action: SessionHealth.NEEDS_ACTION,
  unknown: SessionHealth.NOT_REPORTING,
};

// Per-lifecycle resting label. A single shared value is the default because the
// State column already says WHICH resting state the session is in — repeating it
// here would just be a second copy of that column. Override an individual entry
// when a lifecycle genuinely needs its own wording.
//
// TODO(operator vocabulary): confirm the resting wording. See the note in the
// handoff — the main alternative is "Not monitored", which describes the health
// axis itself ("we are not measuring") rather than restating the lifecycle.
const RESTING_HEALTH = {
  Preparing: SessionHealth.NOT_RUNNING,
  Scheduled: SessionHealth.NOT_RUNNING,
  Completed: SessionHealth.NOT_RUNNING,
  Cancelled: SessionHealth.NOT_RUNNING,
};

// Health labels that mean "an operator should look at this". `Not reporting` is
// deliberately EXCLUDED: losing sight of a session is a visibility gap, not a
// confirmed fault, and session-flow-status.js already caps that class of signal
// at amber for the same reason — routing it here would train operators to
// ignore the Needs Attention tab.
export const ATTENTION_HEALTH = Object.freeze([
  SessionHealth.DELAYED,
  SessionHealth.UNREACHABLE,
  SessionHealth.FAILED,
  SessionHealth.NOT_STREAMING,
  SessionHealth.NEEDS_ACTION,
]);

/**
 * Resolve the health badge for one session.
 *
 * @param {string|null|undefined} rawHealth  backend HealthState, or null when
 *   the poller has no live snapshot for this session's dataflow.
 * @param {string} lifecycle  the normalized lifecycle label (Preparing..Completed).
 */
export function resolveSessionHealth(rawHealth, lifecycle) {
  if (!isRunningLifecycle(lifecycle)) {
    return RESTING_HEALTH[lifecycle] ?? SessionHealth.NOT_RUNNING;
  }
  return LIVE_HEALTH_LABELS[rawHealth] ?? SessionHealth.NOT_REPORTING;
}

export function needsAttention(session) {
  return ATTENTION_HEALTH.includes(session?.health);
}

export function sessionMatchesTab(session, tab) {
  if (tab === "all") return true;
  if (tab === "needs-attention") return needsAttention(session);
  if (tab === "active") return ["Active", "Starting", "Stopping"].includes(session.lifecycle);
  if (tab === "scheduled") return session.lifecycle === "Scheduled";
  if (tab === "completed") return ["Completed", "Cancelled"].includes(session.lifecycle) && !session.archived;
  if (tab === "archived") return session.archived === true;
  return false;
}

export function isRunningLifecycle(lifecycle) {
  return ["Active", "Starting", "Stopping"].includes(lifecycle);
}

export function filterSessions(sessions, tab, search = "") {
  const query = search.trim().toLowerCase();
  return sessions.filter((session) => {
    const matchesSearch =
      !query ||
      session.name.toLowerCase().includes(query) ||
      session.experiment?.toLowerCase().includes(query);
    return sessionMatchesTab(session, tab) && matchesSearch;
  });
}

export function countSessionsForTab(sessions, tab) {
  return sessions.filter((session) => sessionMatchesTab(session, tab)).length;
}

export function summarizeAttentionSessions(sessions, limit = 3) {
  const attentionSessions = sessions.filter((session) => sessionMatchesTab(session, "needs-attention"));
  const visible = attentionSessions.slice(0, limit);

  return {
    total: attentionSessions.length,
    visible,
    hidden: attentionSessions.length - visible.length,
  };
}
