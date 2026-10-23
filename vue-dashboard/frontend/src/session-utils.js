export const sessionTabs = [
  { id: "all", label: "All" },
  { id: "needs-attention", label: "Needs Attention" },
  { id: "active", label: "Active" },
  { id: "scheduled", label: "Scheduled" },
  { id: "completed", label: "Completed" },
  { id: "archived", label: "Archived" },
];

// The backend returns health from a current poller snapshot, or null when none exists.
// Inactive sessions show "Not running". Running sessions without a current report show "Not reporting".
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

// Map backend health states to display labels for running sessions.
// "stopped" means the dataflow stopped while the session still expects it to run.
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

// Inactive sessions share one health label; the State column shows their lifecycle.
// TODO: Confirm whether the label should be "Not running" or "Not monitored".
const RESTING_HEALTH = {
  Preparing: SessionHealth.NOT_RUNNING,
  Scheduled: SessionHealth.NOT_RUNNING,
  Completed: SessionHealth.NOT_RUNNING,
  Cancelled: SessionHealth.NOT_RUNNING,
};

// These health states appear in the Needs Attention tab.
// "Not reporting" indicates missing reports, so it stays out of this list.
// session-flow-status.js displays it as an amber warning.
export const ATTENTION_HEALTH = Object.freeze([
  SessionHealth.DELAYED,
  SessionHealth.UNREACHABLE,
  SessionHealth.FAILED,
  SessionHealth.NOT_STREAMING,
  SessionHealth.NEEDS_ACTION,
]);

/**
 * Return the session's health badge label.
 * @param {string|null|undefined} rawHealth Backend health state, or null without a current report.
 * @param {string} lifecycle Display label such as "Active" or "Completed".
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

const lifecycleLabels = {
  preparing: "Preparing",
  scheduled: "Scheduled",
  starting: "Starting",
  active: "Active",
  stopping: "Stopping",
  completed: "Completed",
  cancelled: "Cancelled",
};

/** Convert a backend status to the label used by session lists and templates. */
export function sessionLifecycleLabel(status) {
  return lifecycleLabels[status] ?? "Unknown";
}

export function normalizeSession(session, fleetSession = {}) {
  const flows = Array.isArray(session.device_flows) ? session.device_flows : [];
  const sinkCount = flows.reduce(
    (total, flow) => total + (Array.isArray(flow?.sinks) ? flow.sinks.length : 0),
    0,
  );
  const lifecycle = sessionLifecycleLabel(session.status);
  const health = resolveSessionHealth(fleetSession.health, lifecycle);

  return {
    id: String(session.id),
    name: session.name,
    lifecycle,
    health,
    experiment: session.experiment_id ? String(session.experiment_id) : null,
    scheduledTime: session.schedule?.start_at ?? null,
    durationSeconds: session.duration_seconds ?? null,
    recordingBounds: Array.isArray(session.recording_bounds) ? session.recording_bounds : [],
    startedAt: session.started_at ?? null,
    endedAt: session.ended_at ?? null,
    fallbackPolicy: session.schedule?.fallback_policy ?? null,
    cancellation: session.cancellation_details ?? session.schedule?.cancellation ?? null,
    deviceCount: flows.length,
    streamCount: flows.length,
    sinkCount,
    // The overview omits watchdog_state. SessionDetailPage reads it from /status.
    watchdog: "Unknown",
    phase: fleetSession.phase ?? null,
    attentionReason: fleetSession.attention_reason ?? null,
    attentionSince: fleetSession.attention_since ?? null,
    policy: session.policy,
    deviceFlows: flows,
    createdAt: session.created_at ?? null,
    isOwner: true,
  };
}

/** Build the operation's display status and warnings without changing its details. */
export function operationOutcome(operation = {}) {
  const state = String(operation.state ?? "").trim().toLowerCase() || "unknown";
  const stop = String(operation.command ?? "").trim().toLowerCase() === "stop";
  const details = operation.details ?? {};
  // A stop succeeds only when the operation confirms shutdown for the whole session.
  // A receipt from one runtime owner cannot confirm that the others stopped.
  const completed = stop && state === "succeeded";
  const warnings = stop && Array.isArray(details.warnings) ? [...details.warnings] : [];
  const result = details.shutdown_result;
  const unclean = result && (result.forced_termination === true || result.forced === true ||
    result.outcome === "forced" || result.clean === false ||
    (result.stream_results ?? []).some((stream) => stream?.forced_termination === true));
  if (stop && (unclean || (details.teardown_confirmed === true && details.output_integrity_confirmed !== true)) &&
      !warnings.some((warning) => warning?.code === "unclean_shutdown")) {
    warnings.push({ code: "unclean_shutdown", message: "Unclean shutdown; output integrity is not confirmed." });
  }
  const label = completed ? warnings.length ? "Completed with warnings" : "Completed"
    : state[0].toUpperCase() + state.slice(1);
  const tone = completed ? warnings.length ? "warn" : "good"
    : state === "succeeded" ? "good" : ["failed", "uncertain"].includes(state) ? "bad" : "neutral";
  return { state: completed ? "succeeded" : state, label, tone, completed, warnings };
}
