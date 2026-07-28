import { requestJson } from "./api-client";
import { resolveSessionHealth } from "./session-utils";

const lifecycleLabels = {
  draft: "Draft",
  scheduled: "Scheduled",
  starting: "Starting",
  active: "Active",
  ending: "Ending",
  stopped: "Stopped",
  completed: "Completed",
};

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

// The name the backend would mint for a session created without one. A preview
// for placeholder text only — send `name: null` to actually get it, since the
// authoritative name is assigned from the row's id at insert time.
export async function loadSessionNameSuggestion() {
  const response = await requestJson("/api/v1/sessions/name-suggestion");
  return typeof response?.name === "string" ? response.name : "";
}

export async function createSessionDraft(payload) {
  return requestJson("/api/v1/sessions/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function startSession(sessionId, options = {}) {
  return requestJson(`/api/v1/sessions/${encodeURIComponent(sessionId)}/commands/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sink_overrides: options.sinkOverrides ?? {}, force: false }),
  });
}

export async function stopSession(sessionId) {
  return requestJson(`/api/v1/sessions/${encodeURIComponent(sessionId)}/commands/stop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ force: false }),
  });
}

export async function completeSession(sessionId) {
  return requestJson(`/api/v1/sessions/${encodeURIComponent(sessionId)}/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
}

export function normalizeSession(session, fleetSession = {}) {
  const flows = Array.isArray(session.device_flows) ? session.device_flows : [];
  const sinkCount = flows.reduce(
    (total, flow) => total + (Array.isArray(flow?.sinks) ? flow.sinks.length : 0),
    0,
  );
  const lifecycle = lifecycleLabels[session.status] ?? "Draft";
  const health = resolveSessionHealth(fleetSession.health, lifecycle);

  return {
    id: String(session.id),
    name: session.name,
    lifecycle,
    health,
    experiment: session.experiment_id ? String(session.experiment_id) : null,
    scheduledTime: session.schedule?.start_at ?? null,
    deviceCount: flows.length,
    streamCount: flows.length,
    sinkCount,
    // The catalog CANNOT know this: /sessions/overview returns only
    // id/name/status/phase/health (session_status.fleet_overview) — there is no
    // watchdog_state on the list payload. This used to be derived from
    // `lifecycle`, which made it a second copy of the State column that
    // additionally reported a bare "Stopped" the operator could not tell apart
    // from the Stopped lifecycle. It stays unresolved here; SessionDetailPage
    // overwrites it with the real `watchdog_state` from /status.
    watchdog: "Unknown",
    phase: fleetSession.phase ?? null,
    policy: session.policy,
    deviceFlows: flows,
    createdAt: session.created_at ?? null,
    isOwner: true,
  };
}
