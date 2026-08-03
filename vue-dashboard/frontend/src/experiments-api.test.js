import { afterEach, expect, it, vi } from "vitest";
import { archiveExperiment, loadExperiments } from "./experiments-api";

afterEach(() => vi.restoreAllMocks());

it("loads non-archived experiments by default", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => [] }));
  vi.stubGlobal("fetch", fetchMock);
  await loadExperiments();
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/experiments?include_archived=false");
});

it("archives through the explicit archive route", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ archived_at: "now" }) }));
  vi.stubGlobal("fetch", fetchMock);
  await archiveExperiment("exp-1");
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/experiments/exp-1/archive");
});
