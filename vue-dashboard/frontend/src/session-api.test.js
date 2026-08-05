import { afterEach, expect, it, vi } from "vitest";
import {
  completeSession,
  createSessionDraft,
  createTemplateRun,
  loadSessionNameSuggestion,
  loadSinkPlan,
  startSession,
  stopSession,
} from "./session-api";

afterEach(() => vi.restoreAllMocks());

it("requests a name suggestion for the selected template", async () => {
  const fetchMock = vi.fn(async () => ({
    ok: true,
    json: async () => ({ name: "sleep analysis • Run 2" }),
  }));
  vi.stubGlobal("fetch", fetchMock);

  await expect(loadSessionNameSuggestion("template revision/2")).resolves.toBe(
    "sleep analysis • Run 2",
  );
  expect(fetchMock.mock.calls[0][0]).toBe(
    "/api/v1/sessions/name-suggestion?source_template_id=template+revision%2F2",
  );
});

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

const TEMPLATE_RUN_PAYLOAD = {
  source_template_id: "tmpl-14",
  expected_template_hash: "a".repeat(64),
  assignments: [{ flow_index: 0, device_config_id: 17, sink_locations: [] }],
};

it("creates a Draft without starting when immediate start was not chosen", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ id: 41, status: "draft" }) }));
  vi.stubGlobal("fetch", fetchMock);

  await expect(createTemplateRun(TEMPLATE_RUN_PAYLOAD)).resolves.toMatchObject({
    draft: { id: 41, status: "draft" },
    started: null,
  });

  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/sessions/");
});

it("creates once and then starts that persisted Draft for immediate start", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ id: 42, status: "draft" }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ id: 42, status: "starting" }) });
  vi.stubGlobal("fetch", fetchMock);

  await expect(
    createTemplateRun(TEMPLATE_RUN_PAYLOAD, { startImmediately: true }),
  ).resolves.toMatchObject({ draft: { id: 42 }, started: { id: 42, status: "starting" } });

  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
    "/api/v1/sessions/",
    "/api/v1/sessions/42/commands/start",
  ]);
});

it("validates before create and makes no request for an invalid run", async () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);

  await expect(
    createTemplateRun({ ...TEMPLATE_RUN_PAYLOAD, assignments: [] }),
  ).rejects.toThrow(/device assignment/i);
  expect(fetchMock).not.toHaveBeenCalled();
});

it("preserves the Draft identity when start fails and never retries create", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ id: 43, status: "draft" }) })
    .mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: async () => ({ code: "device_claim_conflict", detail: "The selected device is busy." }),
    });
  vi.stubGlobal("fetch", fetchMock);

  const error = await createTemplateRun(TEMPLATE_RUN_PAYLOAD, { startImmediately: true }).catch(
    (reason) => reason,
  );

  expect(error.draft).toEqual({ id: 43, status: "draft" });
  expect(error.message).toMatch(/Draft 43 was created/i);
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(fetchMock.mock.calls.filter(([url]) => url === "/api/v1/sessions/")).toHaveLength(1);
});
