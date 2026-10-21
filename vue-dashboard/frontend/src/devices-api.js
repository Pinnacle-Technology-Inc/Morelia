import { requestJson } from "./api-client";

export async function loadDevicePool() {
  const response = await requestJson("/api/v1/devices/pool");
  return normalizeDevicePool(response);
}

export async function startDeviceScan({ signal } = {}) {
  return normalizeDevicePool(await requestJson("/api/v1/devices/scans", { method: "POST", signal }));
}

export async function loadDeviceScan(scanId, { signal } = {}) {
  return normalizeDevicePool(await requestJson(`/api/v1/devices/scans/${encodeURIComponent(scanId)}`, { signal }));
}

function normalizeDevicePool(response) {
  if (!response || typeof response !== "object" || !Array.isArray(response.devices)) {
    throw new TypeError("The device pool API returned an unexpected response shape.");
  }
  return {
    scanId: response.scan_id ?? null,
    scannedAt: response.scanned_at ?? null,
    scanState: response.state ?? "complete",
    revision: response.revision ?? 0,
    completed: response.completed ?? response.devices.length,
    total: response.total ?? response.devices.length,
    scanError: response.error ?? null,
    warnings: Array.isArray(response.warnings) ? response.warnings : [],
    devices: response.devices.map((device) => ({
      ...device,
      // `id` is the persisted device_config_id for configured rows; unconfigured
      // rows have no config yet, so we synthesize a stable key from identity.
      id: device.id ?? `${device.type}:${device.hardware_id ?? device.port}`,
      configId: typeof device.id === "number" ? device.id : null,
      scanKey: device.scan_key ?? `device:${device.hardware_id ?? device.port}`,
      probeState: device.probe_state ?? "complete",
      // Prefer the operator-assigned nickname over the raw discovery `label`
      // (the USB descriptor). The backend sets `label` to the USB descriptor for
      // devices present in the current scan, which would otherwise shadow a saved
      // rename for every plugged-in configured device.
      name: device.nickname ?? device.label ?? device.hardware_id ?? device.port,
      nickname: device.nickname ?? null,
      hardwareId: device.hardware_id ?? null,
      connection: device.connection ?? { preference: typeof device.id === "number" ? "vcp" : "auto" },
      selectedTransport: device.selected_transport ?? null,
      connectionError: connectionErrorMessage(device.connection_error),
      endpoints: device.endpoints ?? [],
      // Config Source + Last Seen depend on backend pool-row fields that do not
      // exist yet (see gap register D-01/D-02). They map through here so the
      // columns light up automatically once the backend emits them.
      configSource: device.source_template ?? null,
      sourceTemplateHash: device.source_template_hash ?? null,
      configurationHash: device.configuration_hash ?? null,
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
  return device?.status === "free" && device?.id != null && device?.availability === "available"
    && (!device.probeState || device.probeState === "complete")
    && !device?.connectionError && !device?.connection_error;
}

export function connectionErrorMessage(error) {
  if (!error) return "";
  if (typeof error === "object" && error.message) return error.message;
  const code = typeof error === "string" ? error : error.code;
  return {
    not_found: "Selected connection not found. Reconnect the device and scan again.",
    enumeration_failed: "The port inventory could not be read. Scan again to check this device.",
    scan_failed: "The scan stopped before this device could be checked. Scan again.",
    not_attempted: "This connection has not been tested. Scan again to check it.",
    probe_failed: "The device did not answer. Check its baud rate and connection.",
    busy: "The device is in use. Close the other application and scan again.",
    claimed: "The device belongs to an active run.",
    identity_ambiguous: "Multiple connections match this identity. Check the connected devices.",
    unsupported_model: "This device model does not support the selected driver.",
    transport_unsupported: "The selected driver is unavailable on this platform.",
    driver_missing: "Install the FTDI D2XX driver and Python package, then scan again.",
    permission_denied: "The selected driver cannot access this device.",
  }[code] ?? code ?? "Connection unavailable";
}

export function deviceConnectionLabel(device) {
  const preference = device?.connection?.preference ?? "vcp";
  const selected = device?.selectedTransport ?? device?.selected_transport;
  return preference === "auto" ? (selected ? `Auto · ${selected.toUpperCase()}` : "Auto") : preference.toUpperCase();
}

async function mutate(path, options) {
  return requestJson(path, { ...options, headers: { "Content-Type": "application/json", ...(options?.headers ?? {}) } });
}

export const loadDeviceConfig = (id) => requestJson(`/api/v1/device-configs/${encodeURIComponent(id)}`);
export async function loadDeviceConfigs() {
  const value = await requestJson("/api/v1/device-configs");
  if (!Array.isArray(value)) throw new TypeError("The device config API returned an unexpected response shape.");
  return value;
}
export const createDeviceConfig = (payload) => mutate("/api/v1/device-configs", { method: "POST", body: JSON.stringify(payload) });
export const createDeviceConfigFromTemplate = (payload) => mutate("/api/v1/device-configs/from-template", { method: "POST", body: JSON.stringify(payload) });
export const nameDeviceConfig = (payload) => mutate("/api/v1/device-configs/name", { method: "POST", body: JSON.stringify(payload) });

// Rename a physical device identity (works whether or not it is configured yet).
// The backend binds the name to an existing config when one exists.
export const registerDeviceName = (payload) => mutate("/api/v1/device-registrations", { method: "POST", body: JSON.stringify(payload) });

// Connection-only patches leave acquisition settings and template provenance intact.
// `editDeviceConfig` accepts { parameters?, connection?, update_source_template?, source_template? }.
// `source_template` (a template file_path or name) is a NEW contract used to
// relink a config to a chosen/new template — see gap register D-04.
export const editDeviceConfig = (id, payload) => mutate(`/api/v1/device-configs/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(payload) });
export const deleteDeviceConfig = (id) => mutate(`/api/v1/device-configs/${encodeURIComponent(id)}`, { method: "DELETE" });

// Canonicalize { type, parameters } server-side and return every device template
// whose content hash matches — NEW contract, see gap register D-03. Lets the UI
// detect whether edited settings already exist as a template.
export const matchDeviceTemplate = (payload) => mutate("/api/v1/device-templates/match", { method: "POST", body: JSON.stringify(payload) });
