import { requestJson } from "./api-client";

export async function loadDeviceTemplates() {
  const value = await requestJson("/api/v1/device-templates");
  if (!Array.isArray(value)) throw new TypeError("The device template API returned an unexpected response shape.");
  return value;
}

export async function loadSessionTemplates() {
  const value = await requestJson("/api/v1/session-templates");
  if (!Array.isArray(value)) throw new TypeError("The session template API returned an unexpected response shape.");
  return value;
}

// Stored templates plus on-disk drafts, tagged by `source`. The browser cannot
// read the session-template directory, so the backend assembles the same
// combined view the CLI builds locally.
export async function loadSessionTemplateCatalog() {
  const value = await requestJson("/api/v1/session-templates/catalog");
  if (!Array.isArray(value)) throw new TypeError("The session template catalog API returned an unexpected response shape.");
  return value;
}

async function send(path, method, body) {
  return requestJson(path, {
    method,
    headers: { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

export const createDeviceTemplate = (payload) => send("/api/v1/device-templates", "POST", payload);
export const updateDeviceTemplate = (name, payload) => send(`/api/v1/device-templates/${encodeURIComponent(name)}`, "PUT", payload);
export const renameDeviceTemplate = (name, newName) => send(`/api/v1/device-templates/${encodeURIComponent(name)}/rename`, "POST", { new_name: newName });
export const deleteDeviceTemplate = (name) => send(`/api/v1/device-templates/${encodeURIComponent(name)}`, "DELETE");
export const createSessionTemplate = (payload) => send("/api/v1/session-templates", "POST", payload);
export const updateSessionTemplate = (name, payload) => send(`/api/v1/session-templates/${encodeURIComponent(name)}`, "PUT", payload);
export const deleteSessionTemplate = (name) => send(`/api/v1/session-templates/${encodeURIComponent(name)}`, "DELETE");
