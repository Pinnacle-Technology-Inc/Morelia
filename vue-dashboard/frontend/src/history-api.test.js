import { afterEach, expect, it, vi } from "vitest";
import { acknowledgeIncident, loadGaps, loadIncidents } from "./history-api";

afterEach(() => vi.restoreAllMocks());

it("loads global incidents with keyset filters", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ items: [], next_cursor: null, has_more: false }) }));
  vi.stubGlobal("fetch", fetchMock);
  await loadIncidents({ status: "open", pageSize: 10, cursor: "opaque" });
  expect(fetchMock.mock.calls[0][0]).toContain("status=open");
  expect(fetchMock.mock.calls[0][0]).toContain("page_size=10");
  expect(fetchMock.mock.calls[0][0]).toContain("cursor=opaque");
});

it("loads gaps and acknowledges without implying resolution", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ items: [], next_cursor: null, has_more: false }) }));
  vi.stubGlobal("fetch", fetchMock);
  await loadGaps({ confidence: "uncertain" });
  await acknowledgeIncident("inc-1", { acknowledgedBy: "operator", note: "checking" });
  expect(fetchMock.mock.calls[0][0]).toContain("confidence=uncertain");
  expect(fetchMock.mock.calls[1][1].body).toContain('"acknowledged_by":"operator"');
});
