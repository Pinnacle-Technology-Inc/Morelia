import { afterEach, expect, it, vi } from "vitest";
import { deleteDeviceTemplate, loadDeviceTemplates, loadSessionTemplateCatalog, loadSessionTemplates } from "./templates-api";

afterEach(() => vi.restoreAllMocks());

it("loads both live template collections", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url) => ({ ok: true, json: async () => url.includes("device") ? [{ name: "d" }] : [{ name: "s" }] })));
  await expect(loadDeviceTemplates()).resolves.toEqual([{ name: "d" }]);
  await expect(loadSessionTemplates()).resolves.toEqual([{ name: "s" }]);
});

it("loads the folder-authoritative session template catalog", async () => {
  const rows = [{ source: "local", name: "draft", reference: "session-templates/draft.toml", content: { policy: "recommend" } }];
  vi.stubGlobal("fetch", vi.fn(async (url) => ({ ok: true, json: async () => (String(url).includes("/catalog") ? rows : []) })));
  await expect(loadSessionTemplateCatalog()).resolves.toEqual(rows);
});

it("uses the destructive device-template route without inventing export", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ warning: "referencing_sessions" }) }));
  vi.stubGlobal("fetch", fetchMock);
  await deleteDeviceTemplate("pod/high");
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/device-templates/pod%2Fhigh");
});
