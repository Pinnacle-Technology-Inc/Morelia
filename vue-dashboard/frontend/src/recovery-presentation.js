import { formatCentralTimestamp } from "./datetime";

const STEPS = {
  detected: ["Disruption detected", "The watchdog detected a stream disruption."],
  settling: ["Allowing the connection to settle", "The source is still being observed before a restart is attempted."],
  stopping_stream: ["Stopping the affected stream", "The old worker and its device connection must close before restarting."],
  checking_presence: ["Checking device presence", "Checking whether the device appears in the hardware inventory."],
  waiting_for_device: ["Waiting for the device", "The device was not found. Recovery can continue when it returns."],
  presence_check_failed: ["Presence check failed", "The hardware inventory check failed. Device presence is unknown."],
  checking_port: ["Checking port access", "Checking whether the device connection can be opened."],
  waiting_for_port: ["Waiting for port access", "The device is present, but its connection is still held. Recovery is waiting for release."],
  restarting_stream: ["Restarting the stream", "Starting a new worker for the affected stream."],
  waiting_for_ping: ["Waiting for PING", "Checking whether the restarted device answers a PING command."],
  waiting_for_data: ["Waiting for fresh data", "Recovery has not yet been verified by a fresh data heartbeat."],
  recovery_verified: ["Recovery verified", "The watchdog recorded proof that recovery succeeded."],
  streaming: ["Streaming", "The watchdog reports that this stream has resumed."],
  awaiting_approval: ["Waiting for approval", "An operator must approve a restart before recovery can continue."],
  cleanup_failed: ["Stream cleanup failed", "Automatic recovery stopped because the previous worker could not be cleaned up. Stop the session before trying again."],
  port_access_timeout: ["Port access timed out", "Automatic recovery stopped because the connection was not released in time. Check the connection and other programs using it."],
  attempts_exhausted: ["Recovery attempts exhausted", "Automatic recovery used its retry budget. Operator intervention is required."],
  restart_failed: ["Stream restart failed", "The restart attempt failed. The latest error below describes the failure."],
  retrying: ["Waiting to retry", "The watchdog is waiting before another recovery attempt."],
  check_failed: ["Recovery check failed", "The recovery check failed. Its result is not proof that the device is disconnected."],
};

const LEGACY_STAGES = {
  unplug_detected: "detected",
  filling_missing_samples: "settling",
  heartbeat_age_exceeded: "settling",
  degraded: "settling",
  recovery_window_expired: "settling",
  stopped_stream_waiting_for_reconnect: "stopping_stream",
  port_check_failed: "presence_check_failed",
  waiting_for_port: "waiting_for_device",
  waiting_for_port_release: "waiting_for_port",
  waiting_for_heartbeat: "waiting_for_data",
  connection_restored: "recovery_verified",
  succeeded: "recovery_verified",
  retry_wait: "retrying",
  failed: "restart_failed",
  port_release_timeout: "port_access_timeout",
};

const FAILED_STEPS = new Set([
  "presence_check_failed", "cleanup_failed", "port_access_timeout", "attempts_exhausted",
  "restart_failed", "check_failed",
]);
const VERIFIED_STEPS = new Set(["recovery_verified", "streaming"]);

function stageLabel(stage) {
  return STEPS[stage]?.[0] ?? "Recovery status unavailable";
}

function epochLabel(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? formatCentralTimestamp(value * 1000)
    : null;
}

function legacyStage(device, diagnostic) {
  const reason = diagnostic.initiating_failure_reason ?? device.reason;
  if (["cleanup_failed", "port_release_timeout"].includes(reason)) {
    return LEGACY_STAGES[reason] ?? reason;
  }
  if (device.recovery_state === "awaiting_approval") return "awaiting_approval";
  if (device.recovery_state === "exhausted") return "attempts_exhausted";
  const action = device.action ?? diagnostic.action;
  const stage = device.recovery_stage ?? diagnostic.recovery?.status;
  if (LEGACY_STAGES[action]) return LEGACY_STAGES[action];
  if (STEPS[action]) return action;
  if (LEGACY_STAGES[stage]) return LEGACY_STAGES[stage];
  if (STEPS[stage]) return stage;
  if (device.recovery_state === "waiting_for_hardware") return "waiting_for_device";
  if (device.recovery_state === "recovered") return "recovery_verified";
  return null;
}

/** Describe reported recovery evidence without inventing completed steps. */
export function deriveRecoveryPresentation(device = {}, diagnostic = {}, {
  lifecycle = "Unknown", telemetryCurrent = false,
} = {}) {
  const progress = device.recovery_progress;
  const hasProgress = Boolean(progress && typeof progress === "object" && progress.stage);
  const stage = hasProgress ? progress.stage : legacyStage(device, diagnostic);
  const current = lifecycle === "Active" && telemetryCurrent;
  const streamStopped = !hasProgress && device.action === "stopped_stream_waiting_for_reconnect";
  const title = streamStopped ? "Stream stopped; awaiting recovery check" : stageLabel(stage);
  const legacyPingFailed = !hasProgress
    && (device.action === "waiting_for_heartbeat" || device.recovery_stage === "waiting_for_heartbeat"
      || diagnostic.action === "waiting_for_heartbeat");
  const pingStatus = progress?.ping_status ?? (legacyPingFailed ? "failed" : null);
  const ping = { pending: "Pending", passed: "Passed", failed: "Failed" }[pingStatus] ?? "Not reported";
  const verification = progress?.verification;
  const freshData = verification === "data"
    || (device.stream_status === "healthy" && diagnostic.heartbeat?.status === "fresh"
      && diagnostic.heartbeat?.packet_count > 0);
  const presence = stage === "presence_check_failed" ? "Presence check failed; unknown"
    : device.hardware_present === true ? "Present"
      : device.hardware_present === false ? "Not present" : "Not reported";
  const count = device.recovery_attempt;
  const max = device.recovery_attempt_max;
  const attempt = Number.isInteger(count) && count >= 0
    ? `${count} of ${Number.isInteger(max) && max > 0 ? max : "unknown"}` : "Not reported";
  let explanation = STEPS[stage]?.[1] ?? "This report does not identify a recovery step.";
  if (streamStopped) explanation = "The affected stream was stopped. The next recovery check has not been reported.";
  if (stage === "waiting_for_data" && pingStatus === "failed") {
    explanation = "PING failed after the restart. The watchdog is waiting for fresh data to verify recovery.";
  }
  if (VERIFIED_STEPS.has(stage)) {
    explanation = verification === "data" ? "Recovery was verified by fresh data."
      : verification === "ping" ? "Recovery was verified by a successful PING."
        : "The watchdog reported recovery success. The verification method was not reported.";
  }
  const history = (Array.isArray(progress?.history) ? progress.history : [])
    .filter((entry) => entry && typeof entry.stage === "string")
    .slice(-16)
    .map((entry) => ({
      stage: entry.stage,
      label: stageLabel(entry.stage),
      at: epochLabel(entry.at),
      attempt: Number.isInteger(entry.attempt) && entry.attempt >= 0 ? entry.attempt : null,
    }));
  return {
    visible: hasProgress || (device.recovery_state != null && device.recovery_state !== "idle") || stage != null,
    stage,
    current,
    title,
    heading: current ? "Current step" : "Last reported step",
    explanation: current ? explanation : "This is the last recorded recovery state. It does not describe current device activity.",
    freshness: current ? null : lifecycle === "Stopping" ? "Session stopping"
      : ["Completed", "Cancelled"].includes(lifecycle) ? "Session closed" : "Current telemetry unavailable",
    tone: !current ? "muted" : FAILED_STEPS.has(stage) ? "bad" : VERIFIED_STEPS.has(stage) ? "good" : "warn",
    startedAt: epochLabel(progress?.started_at),
    attempt,
    presence,
    ping,
    data: freshData ? "Fresh data confirmed" : "Fresh data not confirmed",
    verification: verification === "ping" ? "PING" : verification === "data" ? "Fresh data" : "Not reported",
    lastError: progress?.last_error || diagnostic.failure?.last_error || diagnostic.recovery?.last_error || null,
    history,
    hasProgress,
  };
}
