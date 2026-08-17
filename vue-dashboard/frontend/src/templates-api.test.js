import { afterEach, expect, it, vi } from "vitest";
import {
  canRunTemplate,
  createSessionTemplate,
  deleteDeviceTemplate,
  hasDeviceTemplateDrift,
  loadDeviceTemplates,
  loadSessionTemplateCatalog,
  loadSessionTemplates,
  templateControls,
  templateStateHint,
} from "./templates-api";

afterEach(() => vi.restoreAllMocks());

// A session template is always a registry resource now: it carries a reconciled
// `state`, and the loaders normalize to that shape rather than passing raw rows
// through. Device templates are a different resource and stay untouched.
const REGISTRY_ROW = {
  template_id: "tmpl-1",
  name: "s",
  reference: "s.toml",
  registered_hash: "a".repeat(64),
  observed_hash: "a".repeat(64),
  state: "ACTIVE",
  runnable: true,
  run_blockers: [],
  allowed_actions: ["archive"],
  warnings: [],
  content: { policy: "recommend" },
};

it("loads both live template collections", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url) => ({ ok: true, json: async () => url.includes("device") ? [{ name: "d" }] : [REGISTRY_ROW] })));
  await expect(loadDeviceTemplates()).resolves.toEqual([{ name: "d" }]);
  await expect(loadSessionTemplates()).resolves.toMatchObject([
    { templateId: "tmpl-1", name: "s", state: "ACTIVE", allowedActions: ["archive"] },
  ]);
});

it("loads the folder-authoritative session template catalog", async () => {
  const rows = [{ ...REGISTRY_ROW, template_id: null, name: "draft", reference: "draft.toml", state: "DISCOVERED", allowed_actions: ["register"] }];
  vi.stubGlobal("fetch", vi.fn(async (url) => ({ ok: true, json: async () => (String(url).includes("/catalog") ? rows : []) })));
  await expect(loadSessionTemplateCatalog()).resolves.toMatchObject([
    { templateId: null, name: "draft", state: "DISCOVERED", allowedActions: ["register"] },
  ]);
});

it("refuses a session template row with no reconciled state instead of rendering a guess", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => [{ name: "legacy" }] })));
  await expect(loadSessionTemplates()).rejects.toThrow(/unknown state/);
});

it("does not offer Start run when the backend reports a run blocker", () => {
  const drifted = {
    ...REGISTRY_ROW,
    runnable: false,
    run_blockers: [{
      code: "device_template_changed",
      message: "Flow 1's device template changed after this session revision was accepted.",
      recovery_action: "refresh_dependency_revision",
    }],
    warnings: [
      `flow 1: device template changed at device-templates/df8401.toml: expected ${"a".repeat(64)}, found ${"b".repeat(64)}`,
    ],
  };
  const normalized = {
    ...drifted,
    runnable: drifted.runnable,
    runBlockers: drifted.run_blockers,
  };

  expect(hasDeviceTemplateDrift(drifted)).toBe(true);
  expect(canRunTemplate(normalized)).toBe(false);
  expect(templateControls(normalized).map((control) => control.id)).not.toContain("run");
  expect(templateStateHint(normalized)).toMatch(/device template changed/i);
});

it("normalizes the backend run-gate contract", async () => {
  const blocked = {
    ...REGISTRY_ROW,
    runnable: false,
    run_blockers: [{ code: "device_template_missing", message: "Flow 1's device template is missing." }],
  };
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => [blocked] })));

  await expect(loadSessionTemplates()).resolves.toMatchObject([{
    runnable: false,
    runBlockers: [{ code: "device_template_missing" }],
  }]);
});

it("uses the destructive device-template route without inventing export", async () => {
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ warning: "referencing_sessions" }) }));
  vi.stubGlobal("fetch", fetchMock);
  await deleteDeviceTemplate("pod/high");
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/device-templates/pod%2Fhigh");
});

it("posts a create-template request with only user-meaningful content, no client id/hash", async () => {
  const registered = { template_id: "tmpl-1", name: "bench", state: "ACTIVE" };
  const fetchMock = vi.fn(async () => ({ ok: true, json: async () => registered }));
  vi.stubGlobal("fetch", fetchMock);
  const payload = {
    name: "bench",
    policy: "recommend",
    device_flows: [{ device_template_path: "device-templates/pod-high.toml", sinks: [{ sink_type: "csv", sink_name: "bench-csv" }] }],
  };
  await expect(createSessionTemplate(payload)).resolves.toEqual(registered);
  const [url, options] = fetchMock.mock.calls[0];
  expect(url).toBe("/api/v1/session-templates");
  expect(options.method).toBe("POST");
  expect(JSON.parse(options.body)).toEqual(payload);
});

it("surfaces a 409 duplicate_template response with the existing template attached", async () => {
  const problem = {
    status: 409,
    code: "duplicate_template",
    detail: "Template configuration is already registered.",
    existing_template: { template_id: "tmpl-1", name: "bench", reference: "bench.toml" },
  };
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, json: async () => problem })));
  await expect(createSessionTemplate({ name: "bench-2", device_flows: [] })).rejects.toMatchObject({
    problem: { code: "duplicate_template", existing_template: problem.existing_template },
  });
});
