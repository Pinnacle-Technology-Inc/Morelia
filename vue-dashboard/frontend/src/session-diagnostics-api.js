import { apiUrl, requestJson } from "./api-client";

export const DIAGNOSTICS_VIEWS = Object.freeze(["default", "verbose"]);

export function loadSessionDiagnostics(sessionId, { pageSize = 500, cursor = null } = {}) {
  const query = new URLSearchParams({ page_size: String(pageSize) });
  if (cursor) query.set("cursor", cursor);
  return requestJson(
    `/api/v1/sessions/${encodeURIComponent(String(sessionId))}/diagnostics?${query}`,
  );
}

export function sessionDiagnosticsExportUrl(sessionId, view = "default") {
  if (!DIAGNOSTICS_VIEWS.includes(view)) {
    throw new TypeError(`Unsupported diagnostics view: ${view}`);
  }
  const query = new URLSearchParams({ view });
  return apiUrl(
    `/api/v1/sessions/${encodeURIComponent(String(sessionId))}/diagnostics.txt?${query}`,
  );
}

export async function loadSessionDiagnosticsText(sessionId, view = "default") {
  const response = await fetch(sessionDiagnosticsExportUrl(sessionId, view), {
    headers: { Accept: "text/plain" },
  });
  const body = await response.text();
  if (!response.ok) {
    throw new Error(body || `Diagnostics request failed (${response.status})`);
  }
  return body;
}
