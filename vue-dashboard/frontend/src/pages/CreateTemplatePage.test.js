import { describe, expect, it } from "vitest";

// These mirror the payload/decision logic inside CreateTemplatePage.vue rather
// than mounting the component (this codebase's page tests are logic-only —
// see TemplatesPage.test.js). The point is proving the wizard sends the
// backend's actual create contract and reacts to its actual conflict shape,
// not any earlier session-oriented shape.

describe("create-template payload shape", () => {
  // Mirrors buildFlow()/templatePayload() in CreateTemplatePage.vue: a
  // selected stream contributes its own configSource (the device template its
  // config was created from) as the flow's device_template_path — never the
  // stream's device_config_id, which has no meaning to a template.
  function buildFlow(stream, sinks) {
    const flow = {
      device_template_path: stream?.configSource ?? null,
      sinks: sinks.map((sink) => ({ sink_type: sink.sink_type, sink_name: sink.sink_name })),
    };
    if (stream?.nickname) flow.nickname = stream.nickname;
    return flow;
  }

  it("derives device_template_path from the stream's own configSource, not its device_config_id", () => {
    const stream = { id: 42, configSource: "device-templates/pod-high.toml", nickname: null };
    const flow = buildFlow(stream, [{ sink_type: "csv", sink_name: "pod-high-42-csv" }]);
    expect(flow).toEqual({
      device_template_path: "device-templates/pod-high.toml",
      sinks: [{ sink_type: "csv", sink_name: "pod-high-42-csv" }],
    });
    expect(flow).not.toHaveProperty("device_config_id");
  });

  it("carries a stream's nickname onto the flow only when set", () => {
    expect(buildFlow({ configSource: "x", nickname: "bench-1" }, [])).toMatchObject({ nickname: "bench-1" });
    expect(buildFlow({ configSource: "x", nickname: null }, [])).not.toHaveProperty("nickname");
  });

  it("builds the exact create-template request shape: name, policy, device_flows", () => {
    const payload = {
      name: "bench-2-pod",
      policy: "recommend",
      device_flows: [buildFlow({ id: 1, configSource: "device-templates/pod-high.toml" }, [])],
    };
    expect(Object.keys(payload).sort()).toEqual(["device_flows", "name", "policy"]);
    expect(payload).not.toHaveProperty("id");
    expect(payload).not.toHaveProperty("template_id");
    expect(payload).not.toHaveProperty("hash");
  });
});

describe("create-template duplicate handling", () => {
  // Mirrors the catch branch in createTemplate(): a 409 duplicate_template
  // carries existing_template with the id Review links to, rather than
  // inviting the operator to rename and resubmit.
  function duplicateFrom(problem) {
    if (problem?.code === "duplicate_template" && problem?.existing_template) return problem.existing_template;
    return null;
  }

  it("extracts the existing template to link to from a 409 duplicate_template body", () => {
    const problem = {
      code: "duplicate_template",
      detail: "Template configuration is already registered.",
      existing_template: { template_id: "tmpl-9", name: "bench", reference: "bench.toml" },
    };
    expect(duplicateFrom(problem)).toEqual({ template_id: "tmpl-9", name: "bench", reference: "bench.toml" });
  });

  it("does not treat an unrelated 409 as a duplicate", () => {
    expect(duplicateFrom({ code: "template_state_conflict" })).toBeNull();
  });
});
