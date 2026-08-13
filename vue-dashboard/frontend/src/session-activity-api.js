import { requestJson } from "./api-client";

export function loadSessionActivity(sessionId, { pageSize = 200, cursor = null } = {}) {
  const query = new URLSearchParams({ page_size: String(pageSize) });
  if (cursor) query.set("cursor", cursor);
  return requestJson(
    `/api/v1/sessions/${encodeURIComponent(String(sessionId))}/activity?${query}`,
  );
}
