import { requestJson } from "./api-client";

export async function loadDevicePool() {
  const response = await requestJson("/api/v1/devices/pool");
  if (!response || typeof response !== "object" || !Array.isArray(response.devices)) {
    throw new TypeError("The device pool API returned an unexpected response shape.");
  }
  return {
    scanId: response.scan_id ?? null,
    scannedAt: response.scanned_at ?? null,
    devices: response.devices.map((device) => ({
      ...device,
      // `id` is the persisted device_config_id for configured rows; unconfigured
      // rows have no config yet, so we synthesize a stable key from identity.
      id: device.id ?? `${device.type}:${device.hardware_id ?? device.port}`,
      configId: typeof device.id === "number" ? device.id : null,
      // Prefer the operator-assigned nickname over the raw discovery `label`
      // (the USB descriptor). The backend sets `label` to the USB descriptor for
      // devices present in the current scan, which would otherwise shadow a saved
      // rename for every plugged-in configured device.
      name: device.nickname ?? device.label ?? device.hardware_id ?? device.port,
      nickname: device.nickname ?? null,
      hardwareId: device.hardware_id ?? null,
      // Config Source + Last Seen depend on backend pool-row fields that do not
      // exist yet (see gap register D-01/D-02). They map through here so the
      // columns light up automatically once the backend emits them.
      configSource: device.source_template ?? null,
      sourceTemplateHash: device.source_template_hash ?? null,
      lastSeen: device.last_seen ?? null,
      owningSession: device.owner ?? null,
    })),
  };
}

/**
 * Whether a pool row can be used as a stream.
 *
 * "free" is the pool's term for configured-and-unclaimed, and only a configured
 * row has the persisted `device_config_id` that an assignment or a template flow
 * ultimately needs. Shared by the template wizard and the start-run dialog so
 * both agree on what a pickable device is.
 */
export function isDeviceSelectable(device) {
  return device?.status === "free" && device?.id != null;
}

async function mutate(path, options) {
  return requestJson(path, { ...options, headers: { "Content-Type": "application/json", ...(options?.headers ?? {}) } });
}

export const loadDeviceConfig = (id) => requestJson(`/api/v1/device-configs/${encodeURIComponent(id)}`);
export const createDeviceConfig = (payload) => mutate("/api/v1/device-configs", { method: "POST", body: JSON.stringify(payload) });
export const createDeviceConfigFromTemplate = (payload) => mutate("/api/v1/device-configs/from-template", { method: "POST", body: JSON.stringify(payload) });
export const nameDeviceConfig = (payload) => mutate("/api/v1/device-configs/name", { method: "POST", body: JSON.stringify(payload) });

// Rename a physical device identity (works whether or not it is configured yet).
// The backend binds the name to an existing config when one exists.
export const registerDeviceName = (payload) => mutate("/api/v1/device-registrations", { method: "POST", body: JSON.stringify(payload) });

// `editDeviceConfig` accepts { parameters, update_source_template?, source_template? }.
// `source_template` (a template file_path or name) is a NEW contract used to
// relink a config to a chosen/new template — see gap register D-04.
export const editDeviceConfig = (id, payload) => mutate(`/api/v1/device-configs/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(payload) });
export const deleteDeviceConfig = (id) => mutate(`/api/v1/device-configs/${encodeURIComponent(id)}`, { method: "DELETE" });

// Canonicalize { type, parameters } server-side and return every device template
// whose content hash matches — NEW contract, see gap register D-03. Lets the UI
// detect whether edited settings already exist as a template.
export const matchDeviceTemplate = (payload) => mutate("/api/v1/device-templates/match", { method: "POST", body: JSON.stringify(payload) });
