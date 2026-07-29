import { afterEach, expect, it, vi } from "vitest";
import {
  createDeviceConfig,
  loadDevicePool,
  matchDeviceTemplate,
  registerDeviceName,
} from "./devices-api";

afterEach(() => vi.restoreAllMocks());

it("preserves availability and ownership axes", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({
    scan_id: "scan-1", scanned_at: "2026-07-22T10:00:00Z",
    devices: [{ type: "pod8206hr", port: "COM1", hardware_id: "A1B2C", availability: "unopenable", status: "claimed", owner: 4 }],
  }) })));
  await expect(loadDevicePool()).resolves.toMatchObject({ scanId: "scan-1", devices: [{ availability: "unopenable", status: "claimed", owningSession: 4 }] });
});

it("rejects an unusable pool response", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({}) })));
  await expect(loadDevicePool()).rejects.toThrow("unexpected response shape");
});

it("sends device mutations through the backend contract", async () => {
  const fetchMock = vi.fn(async (_url, options) => ({ ok: true, json: async () => JSON.parse(options.body) }));
  vi.stubGlobal("fetch", fetchMock);
  await createDeviceConfig({ type: "pod8206hr", hardware_id: "A1B2C", port: "COM1", parameters: {} });
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/device-configs", expect.objectContaining({ method: "POST" }));
});

it("maps config identity, source, and last-seen fields for the page", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({
    scan_id: "scan-2", scanned_at: "2026-07-23T10:00:00Z",
    devices: [{
      id: 7, type: "pod8206hr", port: "COM3", hardware_id: "A1B2C", nickname: "Rig A",
      availability: "available", status: "free",
      source_template: "device-templates/pod-high.toml", last_seen: "2026-07-23T10:00:00Z",
    }],
  }) })));
  const pool = await loadDevicePool();
  expect(pool.devices[0]).toMatchObject({
    configId: 7,
    nickname: "Rig A",
    configSource: "device-templates/pod-high.toml",
    lastSeen: "2026-07-23T10:00:00Z",
  });
});

it("routes rename and template matching to their endpoints", async () => {
  const fetchMock = vi.fn(async (_url, options) => ({ ok: true, json: async () => JSON.parse(options.body) }));
  vi.stubGlobal("fetch", fetchMock);
  await registerDeviceName({ type: "pod8206hr", hardware_id: "A1B2C", nickname: "Rig A" });
  await matchDeviceTemplate({ type: "pod8206hr", parameters: { preamp_gain: 10 } });
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/device-registrations", expect.objectContaining({ method: "POST" }));
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/device-templates/match", expect.objectContaining({ method: "POST" }));
});
