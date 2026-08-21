import { afterEach, describe, expect, it, vi } from "vitest";
import { importTemplateFile, templateNameFromFilename } from "./template-import";

afterEach(() => vi.restoreAllMocks());

function selectedFile(name, content) {
  return { name, text: vi.fn(async () => content) };
}

describe("template import routing", () => {
  it("imports session TOML through the TOML endpoint using the filename as its name", async () => {
    const created = { template_id: "tmpl-1", name: "bench" };
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => created }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(importTemplateFile(selectedFile("bench.toml", 'policy = "recommend"'), "session"))
      .resolves.toEqual(created);

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/session-templates/imports");
    expect(JSON.parse(options.body)).toEqual({ name: "bench", toml: 'policy = "recommend"' });
  });

  it("validates device TOML then creates the parsed device template", async () => {
    const parsed = { name: "High gain", type: "pod8206hr", parameters: { preamp_gain: 10 } };
    const created = { name: "High gain", file_path: "device-templates/High gain.toml" };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ content: parsed }) })
      .mockResolvedValueOnce({ ok: true, json: async () => created });
    vi.stubGlobal("fetch", fetchMock);

    await expect(importTemplateFile(selectedFile("renamed.toml", 'name = "High gain"'), "device"))
      .resolves.toEqual(created);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/device-templates/validations");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/device-templates");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual(parsed);
  });

  it("keeps structured JSON import available for either template type", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ name: "bench" }) }));
    vi.stubGlobal("fetch", fetchMock);

    const devicePayload = { name: "device", type: "pod8206hr", parameters: {} };
    await importTemplateFile(selectedFile("device.json", JSON.stringify(devicePayload)), "device");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/device-templates");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual(devicePayload);

    const sessionPayload = { name: "session", policy: "recommend", device_flows: [] };
    await importTemplateFile(selectedFile("session.json", JSON.stringify(sessionPayload)), "session");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/session-templates");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual(sessionPayload);
  });
});

describe("imported template names", () => {
  it("removes only the supported final extension", () => {
    expect(templateNameFromFilename("bench.session.toml")).toBe("bench.session");
    expect(templateNameFromFilename(" device.json ")).toBe("device");
  });
});
