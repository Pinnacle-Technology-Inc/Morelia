import { afterEach, expect, it, vi } from "vitest";
import {
  createTemplateRun,
  loadSessionCatalog,
  loadSessionNameSuggestion,
  stopSession,
} from "./session-api";

afterEach(() => vi.restoreAllMocks());

it("maps overview incident context into the attention card model", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url) => ({
    ok: true,
    json: async () => url.endsWith("/sessions/")
      ? [{
          id: 7,
          name: "attention-card",
          status: "active",
          device_flows: [],
        }]
      : {
          running_count: 1,
          total_count: 1,
          sessions: [{
            id: 7,
            name: "attention-card",
            status: "active",
            health: "failed",
            phase: "running",
            attention_reason: "stream unhealthy",
            attention_since: "2026-08-19T18:42:00+00:00",
          }],
        },
  })));

  const catalog = await loadSessionCatalog();

  expect(catalog.sessions[0]).toMatchObject({
    attentionReason: "stream unhealthy",
    attentionSince: "2026-08-19T18:42:00+00:00",
  });
});

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

it("stops through the guarded route without force", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ status: "stopped" }) }));
  vi.stubGlobal("fetch", fetchMock);
  await stopSession(7);
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/sessions/7/commands/stop");
  expect(fetchMock.mock.calls[0][1].body).toBe('{"force":false}');
});

const TEMPLATE_RUN_PAYLOAD = {
  source_template_id: "tmpl-14",
  expected_template_hash: "a".repeat(64),
  assignments: [{ flow_index: 0, device_config_id: 17, sink_locations: [] }],
  execution: { mode: "immediate" },
};

it.each([null, true, false, "60", 0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1])("rejects invalid duration %s before making a request", async (duration) => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await expect(createTemplateRun({ ...TEMPLATE_RUN_PAYLOAD,
    execution: { mode: "immediate", duration_seconds: duration },
  }, { idempotencyKey: "invalid-duration" })).rejects.toThrow(/duration/i);
  expect(fetchMock).not.toHaveBeenCalled();
});

it("rejects a scheduled duration instead of silently ignoring it", async () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await expect(createTemplateRun({ ...TEMPLATE_RUN_PAYLOAD,
    execution: { mode: "scheduled", start_at: "2030-01-01T00:00:00Z", duration_seconds: 60 },
  }, { idempotencyKey: "scheduled-duration" })).rejects.toThrow(/scheduled runs cannot/i);
  expect(fetchMock).not.toHaveBeenCalled();
});

it("preserves duration and identity across an identical retry", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ id: 41 }) }));
  vi.stubGlobal("fetch", fetchMock);
  const payload = { ...TEMPLATE_RUN_PAYLOAD, execution: { mode: "immediate", duration_seconds: 1800 } };
  await createTemplateRun(payload, { idempotencyKey: "timed-retry" });
  await createTemplateRun(payload, { idempotencyKey: "timed-retry" });
  expect(fetchMock.mock.calls[0][1].body).toBe(fetchMock.mock.calls[1][1].body);
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({
    execution: { duration_seconds: 1800 }, idempotency_key: "timed-retry",
  });
});

it("creates and starts through one idempotent command", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ id: 41, status: "active" }) }));
  vi.stubGlobal("fetch", fetchMock);

  await expect(
    createTemplateRun(TEMPLATE_RUN_PAYLOAD, { idempotencyKey: "request-key-41" }),
  ).resolves.toMatchObject({ id: 41, status: "active" });

  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/session-runs");
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({
    execution: { mode: "immediate" },
    idempotency_key: "request-key-41",
  });
});

it("schedules through the same single command", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ id: 42, status: "scheduled" }) }));
  vi.stubGlobal("fetch", fetchMock);

  await expect(
    createTemplateRun(
      {
        ...TEMPLATE_RUN_PAYLOAD,
        execution: {
          mode: "scheduled",
          start_at: "2026-08-08T12:00:00.000Z",
        },
      },
      { idempotencyKey: "request-key-42" },
    ),
  ).resolves.toMatchObject({ id: 42, status: "scheduled" });

  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/session-runs");
});

it("validates before create and makes no request for an invalid run", async () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);

  await expect(
    createTemplateRun({ ...TEMPLATE_RUN_PAYLOAD, assignments: [] }),
  ).rejects.toThrow(/device assignment/i);
  expect(fetchMock).not.toHaveBeenCalled();
});

it("surfaces a definite rejection without exposing a session", async () => {
  const fetchMock = vi.fn(async () => ({
    ok: false,
    status: 409,
    json: async () => ({ code: "device_claim_conflict", detail: "The selected device is busy." }),
  }));
  vi.stubGlobal("fetch", fetchMock);

  const error = await createTemplateRun(TEMPLATE_RUN_PAYLOAD, { idempotencyKey: "request-key-43" }).catch(
    (reason) => reason,
  );

  expect(error.session).toBeUndefined();
  expect(error.problem.code).toBe("device_claim_conflict");
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
