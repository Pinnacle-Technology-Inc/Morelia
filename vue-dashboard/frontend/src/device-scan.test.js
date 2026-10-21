import { afterEach, expect, it, vi } from "vitest";
import { createDeviceScanController } from "./device-scan";
import { isDeviceSelectable, startDeviceScan, loadDeviceScan } from "./devices-api";

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const snapshot = (revision, scanState = "probing", scanId = "scan-a") => ({
  scanId, revision, scanState, devices: [{ scanKey: "device:serial", probeState: "probing" }],
});
const deferred = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };

it("shows inventory before completion, ignores older revisions, and stops polling at completion", async () => {
  vi.useFakeTimers();
  const updates = [];
  const poll = vi.fn().mockResolvedValueOnce(snapshot(2)).mockResolvedValueOnce(snapshot(1))
    .mockResolvedValueOnce(snapshot(3, "complete"));
  const controller = createDeviceScanController({
    start: async () => snapshot(0, "enumerating"), poll,
    onUpdate: (value) => updates.push(value), onError: (error) => { throw error; },
  });
  const done = controller.refresh();
  await vi.advanceTimersByTimeAsync(0);
  expect(updates.map((item) => item.revision)).toEqual([0]);
  await vi.advanceTimersByTimeAsync(750);
  await done;
  expect(updates.map((item) => item.revision)).toEqual([0, 2, 3]);
  await vi.advanceTimersByTimeAsync(1000);
  expect(poll).toHaveBeenCalledTimes(3);
});

it("does not let a superseded start response replace a newer scan", async () => {
  const old = deferred();
  const onUpdate = vi.fn();
  const start = vi.fn().mockReturnValueOnce(old.promise).mockResolvedValueOnce(snapshot(1, "complete", "new"));
  const controller = createDeviceScanController({ start, onUpdate, onError: vi.fn(), poll: vi.fn() });
  const first = controller.refresh();
  await controller.refresh();
  old.resolve(snapshot(8, "complete", "old"));
  await first;
  expect(onUpdate).toHaveBeenCalledTimes(1);
  expect(onUpdate.mock.calls[0][0].scanId).toBe("new");
  expect(start.mock.calls[0][0].signal.aborted).toBe(true);
});

it("cannot restart a disposed viewer when an earlier save finishes", async () => {
  const save = deferred();
  const start = vi.fn().mockResolvedValue(snapshot(1, "complete"));
  const controller = createDeviceScanController({ start, onUpdate: vi.fn(), onError: vi.fn() });
  const saved = save.promise.then(() => controller.refresh());
  controller.dispose();
  save.resolve();
  await saved;
  expect(start).not.toHaveBeenCalled();
});

it("ignores an in-flight response after the viewer stops", async () => {
  vi.useFakeTimers();
  const response = deferred();
  const onUpdate = vi.fn();
  const poll = vi.fn().mockReturnValue(response.promise);
  const controller = createDeviceScanController({ start: async () => snapshot(0), poll, onUpdate, onError: vi.fn() });
  const done = controller.refresh();
  await vi.advanceTimersByTimeAsync(250);
  controller.stop();
  response.resolve(snapshot(1, "complete"));
  await done;
  expect(onUpdate).toHaveBeenCalledTimes(1);
  expect(poll.mock.calls[0][1].signal.aborted).toBe(true);
});

it("preserves failed scan results and surfaces wrong scan IDs", async () => {
  vi.useFakeTimers();
  const onUpdate = vi.fn();
  const onError = vi.fn();
  const controller = createDeviceScanController({ start: async () => snapshot(0),
    poll: async () => snapshot(1, "complete", "wrong"), onUpdate, onError });
  const done = controller.refresh();
  await vi.advanceTimersByTimeAsync(250);
  await done;
  expect(onError.mock.calls[0][0].message).toContain("different scan ID");
  expect(onUpdate).toHaveBeenCalledTimes(1);
  const failed = createDeviceScanController({ start: async () => snapshot(1, "failed"), onUpdate, onError });
  expect((await failed.refresh()).scanState).toBe("failed");
});

it("uses read-only progress requests and keeps a row key stable when TYPE arrives", async () => {
  const wire = (type, probe_state) => ({ scan_id: "scan-a", state: "probing", revision: 1,
    devices: [{ type, hardware_id: "SERIAL", scan_key: "device:SERIAL", probe_state,
      status: "free", availability: "unverified" }] });
  const fetch = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => wire("unknown", "queued") })
    .mockResolvedValueOnce({ ok: true, json: async () => wire("pod8401hr", "complete") });
  vi.stubGlobal("fetch", fetch);
  const initial = await startDeviceScan();
  const next = await loadDeviceScan(initial.scanId);
  expect(fetch.mock.calls[0][1].method).toBe("POST");
  expect(fetch.mock.calls[1][0]).toBe("/api/v1/devices/scans/scan-a");
  expect(fetch.mock.calls[1][1].method).toBeUndefined();
  expect(next.devices[0].scanKey).toBe(initial.devices[0].scanKey);
  expect(isDeviceSelectable(initial.devices[0])).toBe(false);
});
