import { describe, expect, it } from "vitest";
import {
  compareParameters,
  deviceTemplateForFlow,
  hasDrift,
  defaultSinkStem,
  matchFlowIndex,
  normalizeTemplateRef,
  templateSinksForFlow,
  uniqueSinkIdentifier,
} from "./template-import-utils";

const POD_HIGH = {
  name: "pod-high",
  file_path: "device-templates/pod-high.toml",
  type: "pod8206hr",
  content: { type: "pod8206hr", parameters: { preamp_gain: 10, sample_rate: 2000 } },
  content_hash: "hash-high",
};

const POD_8401 = {
  name: "df8401",
  file_path: "device-templates/df8401.toml",
  type: "pod8401hr",
  content: { type: "pod8401hr", parameters: {} },
  content_hash: "hash-8401",
};

describe("normalizeTemplateRef", () => {
  it("joins the stored path, bare filename and portable name forms", () => {
    const expected = "pod-high";
    expect(normalizeTemplateRef("device-templates/pod-high.toml")).toBe(expected);
    expect(normalizeTemplateRef("pod-high.toml")).toBe(expected);
    expect(normalizeTemplateRef("pod-high")).toBe(expected);
    // Session templates written on Windows carry backslashes.
    expect(normalizeTemplateRef("device-templates\\pod-high.toml")).toBe(expected);
  });

  it("treats a missing reference as empty rather than throwing", () => {
    expect(normalizeTemplateRef(null)).toBe("");
    expect(normalizeTemplateRef(undefined)).toBe("");
    expect(normalizeTemplateRef("")).toBe("");
  });
});

describe("deviceTemplateForFlow", () => {
  it("resolves a flow by its stored device_template_path", () => {
    const flow = { device_template_path: "device-templates/pod-high.toml" };
    expect(deviceTemplateForFlow(flow, [POD_8401, POD_HIGH])).toBe(POD_HIGH);
  });

  it("resolves a local draft's portable device_template name", () => {
    expect(deviceTemplateForFlow({ device_template: "pod-high" }, [POD_HIGH])).toBe(POD_HIGH);
  });

  it("returns null for a flow with no device template link", () => {
    expect(deviceTemplateForFlow({ nickname: "bench" }, [POD_HIGH])).toBeNull();
    expect(deviceTemplateForFlow(null, [POD_HIGH])).toBeNull();
  });

  it("returns null when the referenced template is not in the library", () => {
    expect(deviceTemplateForFlow({ device_template: "deleted" }, [POD_HIGH])).toBeNull();
  });
});

describe("compareParameters", () => {
  it("marks identical parameters as the same", () => {
    const rows = compareParameters({ preamp_gain: 10 }, { preamp_gain: 10 });
    expect(rows).toHaveLength(1);
    expect(rows[0].same).toBe(true);
    expect(hasDrift(rows)).toBe(false);
  });

  it("reports a conflicting value on both sides", () => {
    const rows = compareParameters({ sample_rate: 2000 }, { sample_rate: 500 });
    expect(rows[0]).toMatchObject({
      key: "sample_rate",
      templateValue: 2000,
      deviceValue: 500,
      inTemplate: true,
      inDevice: true,
      same: false,
    });
  });

  it("counts a device parameter the template omits as a difference", () => {
    // Strict rule: the template is the complete picture, so extra device
    // tuning is drift — adopting the template would drop it.
    const rows = compareParameters({ preamp_gain: 10 }, { preamp_gain: 10, lowpass_ch0: 40 });
    const extra = rows.find((row) => row.key === "lowpass_ch0");
    expect(extra).toMatchObject({ inTemplate: false, inDevice: true, deviceValue: 40, same: false });
    expect(hasDrift(rows)).toBe(true);
  });

  it("counts a template parameter the device lacks as a difference", () => {
    const rows = compareParameters({ preamp_gain: 10, sample_rate: 2000 }, { preamp_gain: 10 });
    const missing = rows.find((row) => row.key === "sample_rate");
    expect(missing).toMatchObject({ inTemplate: true, inDevice: false, same: false });
  });

  it("does not treat an explicit null as an absent key", () => {
    const rows = compareParameters({ ss_gain: null }, { ss_gain: null });
    expect(rows[0].same).toBe(true);
    expect(rows[0].inDevice).toBe(true);
  });

  it("compares array values by content, not identity", () => {
    const same = compareParameters({ ss_gain: [1, 5, 5, 5] }, { ss_gain: [1, 5, 5, 5] });
    expect(same[0].same).toBe(true);
    const different = compareParameters({ ss_gain: [1, 5, 5, 5] }, { ss_gain: [5, 5, 5, 5] });
    expect(different[0].same).toBe(false);
  });

  it("returns rows sorted by key so the dialog reads consistently", () => {
    const rows = compareParameters({ sample_rate: 2000, preamp_gain: 10 }, { ttl_pin0: 1 });
    expect(rows.map((row) => row.key)).toEqual(["preamp_gain", "sample_rate", "ttl_pin0"]);
  });

  it("treats two empty parameter sets as matching", () => {
    expect(hasDrift(compareParameters({}, {}))).toBe(false);
  });
});

describe("matchFlowIndex", () => {
  const flows = [
    { device_template_path: "device-templates/pod-high.toml" },
    { device_template_path: "device-templates/df8401.toml" },
    { device_template_path: "device-templates/pod-high.toml" },
  ];
  const library = [POD_HIGH, POD_8401];

  it("picks the first flow whose device template matches the device type", () => {
    expect(matchFlowIndex({ type: "pod8206hr" }, flows, library, [])).toBe(0);
    expect(matchFlowIndex({ type: "pod8401hr" }, flows, library, [])).toBe(1);
  });

  it("skips flows another selection already claimed", () => {
    // Two 8206s must map to the template's two 8206 flows, not both to flow 0.
    expect(matchFlowIndex({ type: "pod8206hr" }, flows, library, [0])).toBe(2);
  });

  it("returns null when every compatible flow is taken", () => {
    expect(matchFlowIndex({ type: "pod8206hr" }, flows, library, [0, 2])).toBeNull();
  });

  it("returns null for a device type the template never asks for", () => {
    expect(matchFlowIndex({ type: "pod8274d" }, flows, library, [])).toBeNull();
  });

  it("returns null when the template has no flows", () => {
    expect(matchFlowIndex({ type: "pod8206hr" }, [], library, [])).toBeNull();
  });
});

describe("uniqueSinkIdentifier", () => {
  it("uses the bare sink type for the first sink of its kind", () => {
    expect(uniqueSinkIdentifier("csv", [])).toBe("csv");
  });

  it("suffixes a second sink of the same type", () => {
    // The backend rejects two sinks named "csv" within one source.
    expect(uniqueSinkIdentifier("csv", [{ sink_type: "csv", sink_name: "" }])).toBe("csv-2");
  });

  it("counts an unnamed sink under the name it will fall back to", () => {
    const existing = [{ sink_type: "csv", sink_name: "" }, { sink_type: "csv", sink_name: "csv-2" }];
    expect(uniqueSinkIdentifier("csv", existing)).toBe("csv-3");
  });

  it("ignores sinks of a different type", () => {
    expect(uniqueSinkIdentifier("csv", [{ sink_type: "plot", sink_name: "" }])).toBe("csv");
  });

  it("respects an operator name that would collide with the generated one", () => {
    expect(uniqueSinkIdentifier("csv", [{ sink_type: "edf", sink_name: "csv" }])).toBe("csv-2");
  });
});

describe("defaultSinkStem", () => {
  it("mirrors the backend's <device_id>-<sink_name> filename", () => {
    const device = { type: "pod8206hr", hardwareId: "ABCDE" };
    expect(defaultSinkStem(device, "csv")).toBe("pod8206hr-ABCDE-csv");
  });

  it("sanitizes separators the way manifests._path_segment does", () => {
    const device = { type: "pod/8206", hardwareId: "A:B\\C" };
    expect(defaultSinkStem(device, "csv")).toBe("pod-8206-A-B-C-csv");
  });

  it("survives a device with no hardware id", () => {
    expect(defaultSinkStem({ type: "pod8206hr" }, "csv")).toBe("pod8206hr--csv");
  });
});

describe("templateSinksForFlow", () => {
  it("imports the canonical sinks[] shape", () => {
    const flow = { sinks: [{ sink_name: "8206-edf", sink_type: "edf" }] };
    expect(templateSinksForFlow(flow)).toEqual([
      { sink_type: "edf", sink_name: "8206-edf", sink_folder: "" },
    ]);
  });

  it("normalizes the legacy flattened shape local drafts still use", () => {
    // dual-device.toml / only82066.toml carry sink_type on the flow itself.
    expect(templateSinksForFlow({ nickname: "bob", sink_type: "csv" })).toEqual([
      { sink_type: "csv", sink_name: "", sink_folder: "" },
    ]);
  });

  it("reads a stored sink_location as a folder, not a filename", () => {
    const flow = { sinks: [{ sink_name: "8206-edf", sink_type: "edf", sink_location: "C:\\data\\run" }] };
    expect(templateSinksForFlow(flow)[0].sink_folder).toBe("C:\\data\\run");
  });

  it("drops a sink_name that is merely the backend's default", () => {
    // library-export.toml writes sink_name = "csv" for a csv sink; keeping it
    // would pin a file called csv.csv instead of using the device-based stem.
    const flow = { sinks: [{ sink_name: "csv", sink_type: "csv" }] };
    expect(templateSinksForFlow(flow)[0].sink_name).toBe("");
  });

  it("carries sink_parameters through so template-only settings survive", () => {
    const flow = { sinks: [{ sink_type: "influx", sink_parameters: { api_token_env: "INFLUX_TOKEN" } }] };
    expect(templateSinksForFlow(flow)[0].sink_parameters).toEqual({ api_token_env: "INFLUX_TOKEN" });
  });

  it("omits sink_parameters entirely when there are none", () => {
    const flow = { sinks: [{ sink_type: "csv", sink_parameters: {} }] };
    expect(templateSinksForFlow(flow)[0]).not.toHaveProperty("sink_parameters");
  });

  it("prefers the sinks[] list when a flow carries both shapes", () => {
    const flow = { sink_type: "csv", sinks: [{ sink_type: "edf" }] };
    expect(templateSinksForFlow(flow).map((sink) => sink.sink_type)).toEqual(["edf"]);
  });

  it("returns nothing for a flow with no sinks at all", () => {
    expect(templateSinksForFlow({ nickname: "bench" })).toEqual([]);
    expect(templateSinksForFlow(null)).toEqual([]);
  });

  it("skips malformed sink entries rather than importing a typeless sink", () => {
    expect(templateSinksForFlow({ sinks: [{ sink_name: "orphan" }, { sink_type: "csv" }] })).toHaveLength(1);
  });
});
