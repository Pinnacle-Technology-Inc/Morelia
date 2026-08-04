import { afterEach, expect, it, vi } from "vitest";
import {
  createSessionTemplate,
  deleteDeviceTemplate,
  loadDeviceTemplates,
  loadSessionTemplateCatalog,
  loadSessionTemplates,
} from "./templates-api";

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
