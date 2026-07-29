import { afterEach, describe, expect, it, vi } from "vitest";
import { loadSessionCatalog } from "./session-api";

afterEach(() => vi.restoreAllMocks());

const session = { id: "live-1", name: "Live session", status: "active", device_flows: [] };

it("returns a degraded live catalog when only the overview request fails", async () => {
  vi.stubGlobal("fetch", vi.fn((url) => url.includes("overview")
    ? Promise.reject(new Error("overview offline"))
    : Promise.resolve({ ok: true, json: async () => [session] })));

  await expect(loadSessionCatalog()).resolves.toMatchObject({
    state: "degraded",
    sessions: [{ id: "live-1", name: "Live session" }],
  });
});

it("fails without rows when the session list request fails", async () => {
  vi.stubGlobal("fetch", vi.fn((url) => url.includes("/sessions/") && !url.includes("overview")
    ? Promise.reject(new Error("backend offline"))
    : Promise.resolve({ ok: true, json: async () => ({ sessions: [] }) })));

  await expect(loadSessionCatalog()).rejects.toThrow("backend offline");
});
