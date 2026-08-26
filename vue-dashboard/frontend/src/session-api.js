import { requestJson } from "./api-client";
import { resolveSessionHealth } from "./session-utils";

const lifecycleLabels = {
  preparing: "Preparing",
  scheduled: "Scheduled",
  starting: "Starting",
  active: "Active",
  stopping: "Stopping",
  completed: "Completed",
  cancelled: "Cancelled",
};

/**
 * The operator-facing name for a wire `status`, for surfaces that show a session
 * without loading one. Exported so the templates catalog reports a run's state in
 * the same words the sessions table does, from one mapping rather than a copy.
 */
export function sessionLifecycleLabel(status) {
  return lifecycleLabels[status] ?? "Unknown";
}

export async function loadSessionCatalog() {
  const [storedResult, fleetResult] = await Promise.allSettled([
    requestJson("/api/v1/sessions/"),
    requestJson("/api/v1/sessions/overview"),
  ]);

  if (storedResult.status === "rejected") {
    throw storedResult.reason instanceof Error
      ? storedResult.reason
      : new Error("Could not load sessions.");
  }

  const storedSessions = storedResult.value;
  const fleet = fleetResult.status === "fulfilled" ? fleetResult.value : null;

  if (!Array.isArray(storedSessions)) {
    throw new TypeError("The session API returned an unexpected response shape.");
  }

  if (fleet && !Array.isArray(fleet.sessions)) {
    throw new TypeError("The session overview API returned an unexpected response shape.");
  }

  const fleetById = new Map((fleet?.sessions ?? []).map((session) => [String(session.id), session]));
  return {
    sessions: storedSessions.map((session) => normalizeSession(session, fleetById.get(String(session.id)))),
    state: fleetResult.status === "fulfilled" ? "live" : "degraded",
    error: fleetResult.status === "fulfilled"
      ? ""
      : fleetResult.reason instanceof Error ? fleetResult.reason.message : "Session overview is unavailable.",
  };
}

// The template-scoped name the backend would mint for a run with no label.
// This is placeholder text only; create() recomputes the authoritative number.
export async function loadSessionNameSuggestion(sourceTemplateId) {
  const query = new URLSearchParams({ source_template_id: sourceTemplateId });
  const response = await requestJson(`/api/v1/sessions/name-suggestion?${query}`);
  return typeof response?.name === "string" ? response.name : "";
}

const FILE_SINK_TYPES = new Set(["csv", "edf", "pvfs"]);

/** Whether a sink type writes a file, and therefore needs a destination. */
export function isFileSink(sinkType) {
  return FILE_SINK_TYPES.has(sinkType);
}

/**
 * Compose one file sink's absolute destination from a chosen folder and name.
 *
 * The extension follows the SINK TYPE rather than anything typed, so a template
 * carrying an EDF sink can never be sent a path ending ".csv", and a name that
 * already spells the extension is not doubled. Returns "" while either half is
 * missing — which is what the start-run form gates its submit on.
 */
export function composeSinkLocation(folder, name, sinkType) {
  const trimmedFolder = String(folder ?? "").trim().replace(/[\\/]+$/, "");
  if (!trimmedFolder || !isFileSink(sinkType)) return "";
  // Separators in a filename would silently make it a subfolder that may not
  // exist; the folder half is the only place a path is chosen.
  const cleanName = String(name ?? "").trim().replace(/[\\/]/g, "-");
  const stem = cleanName.toLowerCase().endsWith(`.${sinkType}`)
    ? cleanName.slice(0, -(sinkType.length + 1))
    : cleanName;
  if (!stem) return "";
  // Read the separator off the folder itself rather than tracking the host's
  // os.sep: a Windows path is unambiguous ("C:\data" can only join with "\").
  const separator = trimmedFolder.includes("\\") ? "\\" : "/";
  return `${trimmedFolder}${separator}${stem}.${sinkType}`;
}

/** Build the only request shape the compact template-run form may submit. */
export function buildTemplateRunPayload({
  template,
  assignments,
  name = "",
  experimentId = "",
  notes = "",
  scheduleAt = "",
  now = new Date(),
} = {}) {
  if (template?.state !== "ACTIVE") throw new TypeError("The selected template is not ACTIVE.");
  if (!template.templateId || !template.registeredHash) {
    throw new TypeError("The selected template revision has no registered identity.");
  }

  const flows = template.content?.device_flows ?? [];
  if (!Array.isArray(assignments) || assignments.length !== flows.length) {
    throw new TypeError("Every template flow needs a device assignment.");
  }

  const runAssignments = assignments.map((assignment) => {
    const flowIndex = Number(assignment.flowIndex);
    const deviceConfigId = Number(assignment.deviceConfigId);
    if (!Number.isInteger(flowIndex) || !Number.isInteger(deviceConfigId) || deviceConfigId <= 0) {
      throw new TypeError("Every template flow needs a valid device assignment.");
    }
    const flow = flows[flowIndex];
    if (!flow) throw new TypeError("A device assignment refers to an unknown template flow.");
    // `assignment.sinks` runs parallel to the template flow's own sink list —
    // the operator edits a destination per sink, never the type or the order,
    // both of which the frozen snapshot owns.
    const edited = Array.isArray(assignment.sinks) ? assignment.sinks : [];
    const sinkLocations = (flow.sinks ?? []).flatMap((sink, sinkIndex) => {
      // Sinks addressed positionally, and only file sinks may carry a location:
      // the backend rejects one on a plot or an Influx sink outright
      // (session_config._locations_by_index).
      if (!isFileSink(sink?.sink_type)) return [];
      const location = composeSinkLocation(
        edited[sinkIndex]?.folder,
        edited[sinkIndex]?.name,
        sink.sink_type,
      );
      // Every file sink in the snapshot must arrive with a location — the
      // backend has no "allocate this one for me" path on a template run — so a
      // blank here is a hole in the form's gating, not an omission to forward.
      if (!location) {
        throw new TypeError("Every file sink needs an output folder and a filename.");
      }
      return [{ sink_index: sinkIndex, sink_location: location }];
    });
    return {
      flow_index: flowIndex,
      device_config_id: deviceConfigId,
      sink_locations: sinkLocations,
    };
  });

  const payload = {
    source_template_id: template.templateId,
    expected_template_hash: template.registeredHash,
    assignments: runAssignments,
  };
  const cleanName = name.trim();
  const cleanExperimentId = experimentId.trim();
  const cleanNotes = notes.trim();
  if (cleanName) payload.name = cleanName;
  if (cleanExperimentId) payload.experiment_id = cleanExperimentId;
  if (cleanNotes) payload.notes = cleanNotes;
  payload.execution = { mode: "immediate" };
  if (scheduleAt) {
    const scheduled = new Date(scheduleAt);
    if (Number.isNaN(scheduled.getTime()) || scheduled <= now) {
      throw new TypeError("Scheduled start must be a valid future time.");
    }
    payload.execution = {
      mode: "scheduled",
      start_at: scheduled.toISOString(),
    };
  }
  return payload;
}

/** A run is pinned to the exact ACTIVE revision the form originally loaded. */
export function templateRevisionChanged(loaded, current) {
  return (
    !current ||
    current.state !== "ACTIVE" ||
    loaded?.templateId !== current.templateId ||
    loaded?.registeredHash !== current.registeredHash
  );
}

export function validateTemplateRunPayload(payload) {
  if (!payload || typeof payload !== "object") throw new TypeError("A template run payload is required.");
  if (!payload.source_template_id || !/^[0-9a-f]{64}$/.test(payload.expected_template_hash ?? "")) {
    throw new TypeError("A registered template ID and hash are required.");
  }
  if (!Array.isArray(payload.assignments) || !payload.assignments.length) {
    throw new TypeError("At least one device assignment is required.");
  }
  for (const assignment of payload.assignments) {
    if (!Number.isInteger(assignment.flow_index) || !Number.isInteger(assignment.device_config_id)) {
      throw new TypeError("Every template flow needs a valid device assignment.");
    }
  }
  if (!payload.execution || !["immediate", "scheduled"].includes(payload.execution.mode)) {
    throw new TypeError("An immediate or scheduled execution mode is required.");
  }
}

/** Create and start now, or create one durable schedule, through one command. */
export async function createTemplateRun(payload, { idempotencyKey, force = false } = {}) {
  validateTemplateRunPayload(payload);
  const key = idempotencyKey || globalThis.crypto?.randomUUID?.();
  if (!key) throw new TypeError("An idempotency key is required to create a run.");
  return requestJson("/api/v1/session-runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, idempotency_key: key, force: Boolean(force) }),
  });
}

export async function stopSession(sessionId, { force = false } = {}) {
  return requestJson(`/api/v1/sessions/${encodeURIComponent(sessionId)}/commands/stop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ force: Boolean(force) }),
  });
}

export async function recoverSession(sessionId, { deviceId, action = "restart" } = {}) {
  const target = String(deviceId ?? "").trim();
  if (!target) throw new TypeError("A recovery target device is required.");
  if (action !== "restart") throw new TypeError("Restart is the only supported recovery action.");
  return requestJson(`/api/v1/sessions/${encodeURIComponent(sessionId)}/commands/recover`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ device_id: target, action }),
  });
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
    fallbackPolicy: session.schedule?.fallback_policy ?? null,
    cancellation: session.cancellation_details ?? session.schedule?.cancellation ?? null,
    deviceCount: flows.length,
    streamCount: flows.length,
    sinkCount,
    // The catalog CANNOT know this: /sessions/overview returns only
    // id/name/status/phase/health (session_status.fleet_overview) — there is no
    // watchdog_state on the list payload. This used to be derived from
    // `lifecycle`, which made it a second copy of the State column that
    // additionally reported a bare "Stopped" the operator could not identify
    // as a runtime state. It stays unresolved here; SessionDetailPage
    // overwrites it with the real `watchdog_state` from /status.
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
