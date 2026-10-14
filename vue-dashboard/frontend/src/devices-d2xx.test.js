import { afterEach, expect, it, vi } from "vitest";
import { deviceConnectionLabel, editDeviceConfig, isDeviceSelectable, loadDevicePool } from "./devices-api";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("keeps native identity and reports the selected automatic route", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ devices: [{
    id: 4, type: "pod8206hr", hardware_id: "001a", port: "001a", status: "free", availability: "available",
    connection: { preference: "auto" }, selected_transport: "d2xx", endpoints: [{ transport: "d2xx" }],
  }] }) })));
  const { devices: [device] } = await loadDevicePool();
  expect(device.hardwareId).toBe("001a");
  expect(deviceConnectionLabel(device)).toBe("Auto · D2XX");
  expect(isDeviceSelectable(device)).toBe(true);
});

it("does not offer a free device with a connection failure", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ devices: [{
    id: 4, type: "pod8206hr", hardware_id: "001a", status: "free",
    connection_error: { code: "driver_missing", message: "Install FTDI D2XX" },
  }] }) })));
  const { devices: [device] } = await loadDevicePool();
  expect(device.connectionError).toBe("Install FTDI D2XX");
  expect(isDeviceSelectable(device)).toBe(false);
});

it("sends connection-only edits without acquisition parameters", async () => {
  const fetchMock = vi.fn(async (_url, options) => ({ ok: true, json: async () => JSON.parse(options.body) }));
  vi.stubGlobal("fetch", fetchMock);
  await editDeviceConfig(4, { connection: { preference: "d2xx", baudrate: 115200 } });
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ connection: { preference: "d2xx", baudrate: 115200 } });
});

it.each(["not_found", "unavailable", "unopenable", "unverified", undefined])("blocks a free device whose connection is %s", (availability) => {
  expect(isDeviceSelectable({ id: 4, status: "free", availability })).toBe(false);
});

it("retains native-driver warnings alongside successfully scanned VCP devices", async () => {
  const warning = {
    transport: "d2xx", code: "backend_unavailable",
    message: "Native D2XX requires ftd2xx and the FTDI native library",
  };
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({
    warnings: [warning], devices: [{ id: 4, hardware_id: "001a", port: "COM9", status: "free", availability: "available" }],
  }) })));
  const pool = await loadDevicePool();
  expect(pool.warnings).toEqual([warning]);
  expect(pool.devices).toHaveLength(1);
  expect(isDeviceSelectable(pool.devices[0])).toBe(true);
});

it("retains a scan warning even when no devices were found", async () => {
  const warning = { transport: "d2xx", code: "enumeration_failed", message: "FTDI enumeration failed" };
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ warnings: [warning], devices: [] }) })));
  await expect(loadDevicePool()).resolves.toMatchObject({ warnings: [warning], devices: [] });
});

it("accepts older pool responses that have no warning field", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ devices: [] }) })));
  await expect(loadDevicePool()).resolves.toMatchObject({ warnings: [] });
});
