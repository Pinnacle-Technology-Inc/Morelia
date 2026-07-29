import { requestJson } from "./api-client";

function queryString(params) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  }
  return query.toString();
}

export function loadIncidents({ session, status, pageSize = 50, cursor = null } = {}) {
  const query = queryString({ session, status, page_size: pageSize, cursor });
  return requestJson(`/api/v1/incidents?${query}`);
}

export function loadGaps({ session, confidence, pageSize = 50, cursor = null } = {}) {
  const query = queryString({ session, confidence, page_size: pageSize, cursor });
  return requestJson(`/api/v1/gaps?${query}`);
}

export function acknowledgeIncident(incidentId, { acknowledgedBy, note } = {}) {
  return requestJson(`/api/v1/incidents/${encodeURIComponent(incidentId)}/ack`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ acknowledged_by: acknowledgedBy || undefined, note: note || undefined }),
  });
}
