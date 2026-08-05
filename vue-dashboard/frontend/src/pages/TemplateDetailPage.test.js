import { afterEach, describe, expect, it, vi } from "vitest";
import {
  acceptTemplateChange,
  archiveTemplate,
  normalizeTemplate,
  registerDiscoveredTemplate,
  resolveTemplateRename,
  templateStateHint,
} from "../templates-api";

afterEach(() => vi.restoreAllMocks());

function stubResponse(body) {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => body }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const ACCEPTED_REVISION = {
  template_id: "tmpl-2",
  name: "bench",
  reference: "bench.toml",
  registered_hash: "b".repeat(64),
  observed_hash: "b".repeat(64),
  state: "ACTIVE",
  lifecycle_state: "ACTIVE",
  integrity_state: "MATCHED",
  lineage_parent_id: "tmpl-1",
  allowed_actions: ["archive"],
  warnings: [],
};

describe("registry actions call their own dedicated route", () => {
  it("accepts a change by internal id and returns the NEW revision", async () => {
    const fetchMock = stubResponse(ACCEPTED_REVISION);

    const result = await acceptTemplateChange("tmpl-1");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/session-templates/tmpl-1/actions/accept-change");
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
    // The new revision has its own id and inherits lineage — the old row is not
    // mutated in place, so run history stays attached to the revision that made it.
    expect(result.templateId).toBe("tmpl-2");
    expect(result.lineageParentId).toBe("tmpl-1");
    expect(result.state).toBe("ACTIVE");
  });

  it("registers a discovered file by its flat reference", async () => {
    const fetchMock = stubResponse({ ...ACCEPTED_REVISION, state: "ACTIVE" });

    await registerDiscoveredTemplate("bench draft.toml");

    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/v1/session-templates/bench%20draft.toml/actions/register",
    );
  });

  it("archives by internal id", async () => {
    const fetchMock = stubResponse({ ...ACCEPTED_REVISION, state: "ARCHIVED", allowed_actions: [] });

    const result = await archiveTemplate("tmpl-2");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/session-templates/tmpl-2/actions/archive");
    expect(result.state).toBe("ARCHIVED");
    expect(result.allowedActions).toEqual([]);
  });

  it("resolves an ambiguous rename with the operator's chosen file", async () => {
    const fetchMock = stubResponse(ACCEPTED_REVISION);

    await resolveTemplateRename("tmpl-1", "renamed-bench.toml");

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/session-templates/tmpl-1/actions/resolve-rename");
    // The server picks nothing by scan order; the selection is explicit.
    expect(JSON.parse(options.body)).toEqual({ selected_relative_path: "renamed-bench.toml" });
  });
});

describe("revision diagnostics", () => {
  it("keeps trusted and observed hashes distinct on a drifted file", () => {
    const template = normalizeTemplate({
      template_id: "tmpl-1",
      name: "bench",
      reference: "bench.toml",
      registered_hash: "a".repeat(64),
      observed_hash: "c".repeat(64),
      state: "CHANGED",
      allowed_actions: ["accept_change", "archive"],
      warnings: [],
    });

    expect(template.registeredHash).not.toBe(template.observedHash);
    expect(templateStateHint(template)).toMatch(/no longer matches the accepted revision/i);
  });

  it("explains why each non-runnable state cannot run", () => {
    for (const state of ["DISCOVERED", "PENDING", "DUPLICATE", "AMBIGUOUS_RENAME", "CHANGED", "ARCHIVED", "MISSING", "INVALID"]) {
      const template = normalizeTemplate({
        name: "x", reference: "x.toml", state, allowed_actions: [], warnings: [],
      });
      expect(templateStateHint(template)).not.toBe("");
    }
    // ACTIVE needs no explanation — it simply works.
    expect(templateStateHint({ state: "ACTIVE" })).toBe("");
  });
});
