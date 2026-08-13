import { apiUrl, requestJson } from "./api-client";

export function loadSessionDiagnostics(sessionId, { pageSize = 500, cursor = null } = {}) {
  const query = new URLSearchParams({ page_size: String(pageSize) });
  if (cursor) query.set("cursor", cursor);
  return requestJson(
    `/api/v1/sessions/${encodeURIComponent(String(sessionId))}/diagnostics?${query}`,
  );
}

export function sessionDiagnosticsExportUrl(sessionId) {
  return apiUrl(
    `/api/v1/sessions/${encodeURIComponent(String(sessionId))}/diagnostics.txt`,
  );
}
