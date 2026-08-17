import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  loadSessionDiagnostics,
  loadSessionDiagnosticsText,
  sessionDiagnosticsExportUrl,
} from "./session-diagnostics-api";

const diagnosticLogSource = readFileSync(
  new URL("./components/SessionDiagnosticLog.vue", import.meta.url),
  "utf8",
);

afterEach(() => vi.restoreAllMocks());

describe("session diagnostics API", () => {
  it("loads a bounded, cursor-paginated page for one encoded session", async () => {
    const page = { items: [], has_more: false, next_cursor: null };
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => page,
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      loadSessionDiagnostics("run/a", { pageSize: 250, cursor: "next page" }),
    ).resolves.toEqual(page);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/sessions/run%2Fa/diagnostics?page_size=250&cursor=next+page",
      expect.objectContaining({
        headers: expect.objectContaining({ Accept: "application/json" }),
      }),
    );
  });

  it("defaults the plain-text support export URL to Human", () => {
    expect(sessionDiagnosticsExportUrl("run/a")).toBe(
      "/api/v1/sessions/run%2Fa/diagnostics.txt?view=human",
    );
  });

  it("loads and downloads the explicitly selected diagnostics view", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      text: async () => "verbose diagnostics",
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(loadSessionDiagnosticsText("run/a", "verbose")).resolves.toBe(
      "verbose diagnostics",
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/sessions/run%2Fa/diagnostics.txt?view=verbose",
      expect.objectContaining({
        headers: expect.objectContaining({ Accept: "text/plain" }),
      }),
    );
    expect(sessionDiagnosticsExportUrl("run/a", "verbose")).toBe(
      "/api/v1/sessions/run%2Fa/diagnostics.txt?view=verbose",
    );
  });

  it("integrates an accessible Human and Verbose selector in the existing log UI", () => {
    expect(diagnosticLogSource).toContain('value="human"');
    expect(diagnosticLogSource).toContain('value="verbose"');
    expect(diagnosticLogSource).toContain("Readable diagnostics with repetitive telemetry");
    expect(diagnosticLogSource).toContain("Complete raw telemetry including IDs");
    expect(diagnosticLogSource).toContain("loadSessionDiagnosticsText(props.sessionId, view.value)");
    expect(diagnosticLogSource).toContain("sessionDiagnosticsExportUrl(props.sessionId, view.value)");
  });
});
