import { afterEach, expect, it, vi } from "vitest";
import { loadSystemHealth, shutdownControlPlane } from "./system-health-api";

afterEach(() => vi.restoreAllMocks());

it("loads health facts independently and preserves partial failures", async () => {
  const fetchMock = vi.fn(async (url) => {
    if (url === "/api/v1/runtimes/") throw new Error("runtime unavailable");
    return { ok: true, json: async () => (url === "/ready" ? { ready: true, checks: {} } : {}) };
  });
  vi.stubGlobal("fetch", fetchMock);
  const result = await loadSystemHealth();
  expect(result.ready.checks).toEqual({});
  expect(result.runtimes).toEqual([]);
  expect(result.errors).toEqual(["runtime unavailable"]);
});

it("sends explicit force intent for control-plane shutdown", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ shutdown_scheduled: true }) }));
  vi.stubGlobal("fetch", fetchMock);
  await shutdownControlPlane(true);
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/runtimes/control-plane-shutdown");
  expect(fetchMock.mock.calls[0][1].body).toBe('{"force":true}');
});
