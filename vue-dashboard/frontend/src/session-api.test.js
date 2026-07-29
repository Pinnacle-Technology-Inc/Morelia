import { afterEach, expect, it, vi } from "vitest";
import {
  completeSession,
  createSessionDraft,
  loadSinkPlan,
  startSession,
  stopSession,
} from "./session-api";

afterEach(() => vi.restoreAllMocks());

it("posts a canonical draft exactly once", async () => {
  const fetchMock = vi.fn(async (_url, options) => ({ ok: true, json: async () => JSON.parse(options.body) }));
  vi.stubGlobal("fetch", fetchMock);
  await createSessionDraft({ name: "Draft", policy: "recommend", device_flows: [] });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[0][1].body).toContain('"device_flows":[]');
});

it("starts a persisted draft without forcing claims", async () => {
  const fetchMock = vi.fn(async (_url, options) => ({ ok: true, json: async () => JSON.parse(options.body) }));
  vi.stubGlobal("fetch", fetchMock);
  await startSession(7);
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/sessions/7/commands/start");
  expect(fetchMock.mock.calls[0][1].body).toContain('"force":false');
});

it("stops through the guarded route without force", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ status: "stopped" }) }));
  vi.stubGlobal("fetch", fetchMock);
  await stopSession(7);
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/sessions/7/commands/stop");
  expect(fetchMock.mock.calls[0][1].body).toBe('{"force":false}');
});

it("reads the sink plan without mutating anything", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ sinks: [] }) }));
  vi.stubGlobal("fetch", fetchMock);
  await loadSinkPlan(19);
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/sessions/19/sink-plan");
  expect(fetchMock.mock.calls[0][1]?.method ?? "GET").toBe("GET");
});

it("carries operator-chosen output names into the start command", async () => {
  const fetchMock = vi.fn(async (_url, options) => ({ ok: true, json: async () => JSON.parse(options.body) }));
  vi.stubGlobal("fetch", fetchMock);
  await startSession(19, { sinkOverrides: { "peter:8206-edf": "C:/out/run-2.edf" } });
  const body = JSON.parse(fetchMock.mock.calls[0][1].body);
  expect(body.sink_overrides).toEqual({ "peter:8206-edf": "C:/out/run-2.edf" });
});

it("completes through its distinct terminal route", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ status: "completed" }) }));
  vi.stubGlobal("fetch", fetchMock);
  await completeSession(7);
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/sessions/7/complete");
});
