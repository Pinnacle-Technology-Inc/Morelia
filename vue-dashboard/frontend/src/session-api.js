import { requestJson } from "./api-client";

const lifecycleLabels = {
  draft: "Draft",
  scheduled: "Scheduled",
  starting: "Starting",
  active: "Active",
  ending: "Ending",
  completed: "Completed",
};

const healthLabels = {
  healthy: "Healthy",
  suspect: "Suspect",
  recovering: "Recovering",
  delayed: "Needs action",
  unreachable: "Needs action",
  failed: "Needs action",
  needs_action: "Needs action",
  stopped: "Unknown",
  unknown: "Unknown",
};

export async function loadSessionCatalog() {
  const [storedSessions, fleet] = await Promise.all([
    requestJson("/api/v1/sessions/"),
    requestJson("/api/v1/sessions/overview"),
  ]);

  if (!Array.isArray(storedSessions) || !Array.isArray(fleet?.sessions)) {
    throw new TypeError("The session API returned an unexpected response shape.");
  }

  const fleetById = new Map(fleet.sessions.map((session) => [String(session.id), session]));
  return storedSessions.map((session) => normalizeSession(session, fleetById.get(String(session.id))));
}

export function normalizeSession(session, fleetSession = {}) {
  const flows = Array.isArray(session.device_flows) ? session.device_flows : [];
  const sinkCount = flows.reduce(
    (total, flow) => total + (Array.isArray(flow?.sinks) ? flow.sinks.length : 0),
    0,
  );
  const lifecycle = lifecycleLabels[session.status] ?? "Draft";
  const health = healthLabels[fleetSession.health] ?? "Unknown";

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
    watchdog: ["Active", "Starting", "Ending"].includes(lifecycle) ? "Unknown" : "Stopped",
    phase: fleetSession.phase ?? null,
    policy: session.policy,
    deviceFlows: flows,
    createdAt: session.created_at ?? null,
    isOwner: true,
  };
}
