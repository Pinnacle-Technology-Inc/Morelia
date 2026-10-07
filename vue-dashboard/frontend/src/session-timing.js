import { timestampMs } from "./datetime";
import { operationOutcome } from "./session-utils";

// JavaScript stores milliseconds; Python's datetime ends within this last millisecond.
const PYTHON_DATETIME_MAX_MS = Date.parse("9999-12-31T23:59:59.999Z");

export function maxDurationSeconds(startAt = Date.now()) {
  const started = timestampMs(startAt);
  if (started === null) throw new TypeError("A valid start time is required.");
  return Math.max(0, Math.floor((PYTHON_DATETIME_MAX_MS - started) / 1000));
}

export function validateDurationSeconds(seconds, startAt = Date.now()) {
  if (!Number.isSafeInteger(seconds) || seconds < 1) {
    throw new TypeError("Duration must be a positive whole number of seconds represented exactly.");
  }
  const maximum = maxDurationSeconds(startAt);
  if (seconds > maximum) {
    throw new TypeError(`Duration must be at most ${maximum} seconds from the start time. The deadline cannot exceed Python's datetime maximum (9999-12-31 UTC).`);
  }
  return seconds;
}

export function durationSecondsFromMinutes(minutes, startAt = Date.now()) {
  // Input elements provide strings. Accept ordinary whole decimal minutes only.
  const validInput = typeof minutes === "number" ||
    (typeof minutes === "string" && /^\d+$/.test(minutes.trim()));
  const value = validInput ? Number(minutes) : Number.NaN;
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError("Enter positive whole minutes within the supported numeric precision.");
  }
  return validateDurationSeconds(value * 60, startAt);
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
  const timed = Number.isSafeInteger(duration) && duration > 0 && duration <= maxDurationSeconds(started ?? now);
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
