import { timestampMs } from "./datetime";
import { operationOutcome } from "./session-utils";

export const MAX_DURATION_SECONDS = 2147483647; //Max value for signed 32-bit integer
export const MAX_DURATION_MINUTES = Math.floor(MAX_DURATION_SECONDS / 60);

export function validateDurationSeconds(seconds) {
  if (!Number.isInteger(seconds) || seconds < 1 || seconds > MAX_DURATION_SECONDS) {
    throw new TypeError(`Duration must be a whole number of seconds from 1 to ${MAX_DURATION_SECONDS}.`);
  }
  return seconds;
}

export function durationSecondsFromMinutes(minutes) {
  // Input elements provide strings. Accept ordinary whole decimal minutes only.
  const validInput = typeof minutes === "number" ||
    (typeof minutes === "string" && /^\d+$/.test(minutes.trim()));
  const value = validInput ? Number(minutes) : Number.NaN;
  if (!Number.isInteger(value) || value < 1 || value > MAX_DURATION_MINUTES) {
    throw new TypeError(`Enter whole minutes from 1 to ${MAX_DURATION_MINUTES}.`);
  }
  return value * 60;
}

export function formatDuration(seconds) {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 3600)}h ${String(Math.floor((whole % 3600) / 60)).padStart(2, "0")}m ${String(whole % 60).padStart(2, "0")}s`;
}

/** Display-only: clocks never issue Stop or infer that cleanup has completed. */
export function sessionTiming(session, now = Date.now()) {
  const started = timestampMs(session?.startedAt);
  const ended = timestampMs(session?.endedAt);
  const duration = session?.durationSeconds;
  const timed = Number.isInteger(duration) && duration > 0 && duration <= MAX_DURATION_SECONDS;
  const terminal = ["completed", "cancelled", "stopped"].includes(String(session?.lifecycle ?? "").toLowerCase());
  const stopping = String(session?.lifecycle ?? "").toLowerCase() === "stopping";
  const deadline = started !== null && timed ? started + duration * 1000 : null; //Calculate everything in miliseconds
  const recordedSeconds = started !== null && ended !== null && ended >= started
    ? (ended - started) / 1000 : null;
  const remainingSeconds = deadline !== null && !terminal && !stopping
    ? Math.max(0, Math.ceil((deadline - now) / 1000)) : null;
  const recordedLabel = recordedSeconds !== null ? formatDuration(recordedSeconds)
    : started === null && timed && !terminal ? "Waiting for data" : "Recording timing unavailable";
  const remainingLabel = !timed ? null : terminal ? "Run ended" : stopping ? "Stopping"
    : started === null ? "Waiting for data"
      : remainingSeconds === 0 ? "Duration reached; awaiting stop confirmation" : formatDuration(remainingSeconds);
  return {
    timed, // true for a valid duration limit; false for an unlimited/invalid duration.
    deadlineMs: deadline, // Unix timestamp in milliseconds, or null before data starts/without a valid limit.
    recordedLabel, // First-to-last recorded span ("0h 10m 00s")
    limitLabel: timed ? formatDuration(duration) : "Unlimited", // Requested duration ("0h 30m 00s"), or "Unlimited".
    remainingLabel, // Countdown ("0h 20m 00s"), a status message, or null for an unlimited run.
  };
}

/** A reason is a trigger, never a claim that shutdown succeeded. */
export function sessionStopExplanation(session, operations = []) {
  const stops = (operations ?? []).filter((operation) => String(operation.command).toLowerCase() === "stop");
  const operation = [...stops].sort((a, b) =>
    (timestampMs(b.created_at) ?? 0) - (timestampMs(a.created_at) ?? 0),
  ).find((item) => item.details?.stop_reason);
  if (!operation) return null;
  const reason = operation.details.stop_reason;
  const terminal = ["completed", "cancelled", "stopped"].includes(String(session.lifecycle).toLowerCase());
  const requestedAt = timestampMs(operation.details.requested_at ?? operation.created_at);
  const timing = sessionTiming(session);
  const deadline = timing.deadlineMs;
  const scheduled = timestampMs(session.scheduledTime);
  let label;
  if (reason === "user_stop") {
    label = terminal ? "Stopped by user" : "User stop requested";
    if (scheduled !== null && requestedAt !== null && requestedAt < scheduled && !session.startedAt) {
      label += " before scheduled start";
    } else if (timing.timed && (!session.startedAt || (requestedAt !== null && deadline !== null && requestedAt < deadline))) {
      label += " before duration ended";
    }
  } else {
    label = {
      duration_ended: "Requested duration ended",
      application_shutdown: "Application shutdown requested termination",
      runtime_failure: "Runtime failure requested termination",
    }[reason] ?? reason;
  }
  const outcome = operationOutcome(operation);
  const state = outcome.state;
  if (["failed", "uncertain"].includes(state)) label += ` — shutdown ${state}`;
  if (outcome.warnings.length) {
    if (outcome.completed) label += " — completed with warnings";
    label += ` — ${outcome.warnings.map((warning) => warning.message || warning.code).join("; ").replace(/^Unclean/, "unclean").replace(/\.$/, "")}`;
  }
  return label;
}
