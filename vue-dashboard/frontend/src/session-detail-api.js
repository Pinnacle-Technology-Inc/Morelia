import { requestJson } from "./api-client";

const COLLECTION_FIELDS = ["runtimes", "operations", "incidents", "gaps", "sinks"];

export async function loadSessionDetail(sessionId) {
  if (typeof sessionId !== "number" && typeof sessionId !== "string") {
    throw new TypeError("A numeric or string session id is required.");
  }

  const response = await requestJson(`/api/v1/sessions/${encodeURIComponent(String(sessionId))}/status`);
  return normalizeSessionDetail(response);
}

export function normalizeSessionDetail(response) {
  if (!response || typeof response !== "object" || !response.session || typeof response.session !== "object") {
    throw new TypeError("The session status API returned an unusable response shape.");
  }

  const model = { ...response };
  for (const field of COLLECTION_FIELDS) {
    model[field] = Array.isArray(response[field]) ? response[field] : [];
  }
  return model;
}
