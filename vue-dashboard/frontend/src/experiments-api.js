import { requestJson } from "./api-client";

export function loadExperiments({ includeArchived = false } = {}) {
  return requestJson(`/api/v1/experiments?include_archived=${includeArchived ? "true" : "false"}`);
}

export function createExperiment(payload) {
  return requestJson("/api/v1/experiments", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
}

export function updateExperiment(id, payload) {
  return requestJson(`/api/v1/experiments/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function archiveExperiment(id) {
  return requestJson(`/api/v1/experiments/${encodeURIComponent(id)}/archive`, { method: "POST" });
}

export function deleteExperiment(id) {
  return requestJson(`/api/v1/experiments/${encodeURIComponent(id)}`, { method: "DELETE" });
}
