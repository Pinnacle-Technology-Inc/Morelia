import { requestJson } from "./api-client";

export function loadSessionNotes(sessionId, { limit = 100, beforeId = null } = {}) {
  const query = new URLSearchParams({ limit: String(limit) });
  if (beforeId !== null && beforeId !== undefined) {
    query.set("before_id", String(beforeId));
  }
  return requestJson(`/api/v1/sessions/${sessionId}/notes?${query}`);
}

export function createSessionNote(sessionId, { body, showTimestamp = false }) {
  return requestJson(`/api/v1/sessions/${sessionId}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body, show_timestamp: showTimestamp }),
  });
}

export function updateSessionNote(sessionId, noteId, { body, showTimestamp }) {
  return requestJson(`/api/v1/sessions/${sessionId}/notes/${noteId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body, show_timestamp: showTimestamp }),
  });
}
