import { afterEach, describe, expect, it, vi } from "vitest";
import { loadSessionDetail, normalizeSessionDetail } from "./session-detail-api";

afterEach(() => vi.restoreAllMocks());

const snapshot = {
  session: { id: "42", name: "Live session", status: "active" },
  health: null,
  phase: "running",
  latest_report: { devices: [{ device_id: "dev-a", stream_status: "suspect" }] },
  runtimes: [],
  operations: [],
  incidents: [],
  gaps: [],
  sinks: [],
  runtime_id: null,
  watchdog_id: null,
  watchdog_state: null,
  recovery: null,
};

it("loads a numeric or string id with URL encoding and preserves status axes", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => snapshot }));
  vi.stubGlobal("fetch", fetchMock);

  await expect(loadSessionDetail("a/b")).resolves.toMatchObject({
    session: snapshot.session,
    latest_report: snapshot.latest_report,
    health: null,
  });
  expect(fetchMock).toHaveBeenCalledWith("/api/v1/sessions/a%2Fb/status", expect.any(Object));
});

it("normalizes absent collections without inventing state", () => {
  const model = normalizeSessionDetail({ session: { id: 7 }, health: null });
  expect(model).toMatchObject({
    session: { id: 7 },
    health: null,
    runtimes: [],
    operations: [],
    incidents: [],
    gaps: [],
    sinks: [],
  });
  expect(model.phase).toBeUndefined();
});

it("rejects a structurally unusable response", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({}) })));
  await expect(loadSessionDetail(7)).rejects.toThrow("unusable response shape");
});
