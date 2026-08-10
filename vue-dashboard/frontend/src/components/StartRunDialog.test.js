import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  buildTemplateRunPayload,
  composeSinkLocation,
  isFileSink,
  templateRevisionChanged,
} from "../session-api";

// A template's stored sink_location is a FOLDER, not a file path — a template is
// a reusable recipe, so its destination means "put this run's output here".
// See templateSinksForFlow in template-import-utils.js.
const ACTIVE_TEMPLATE = {
  templateId: "tmpl-14",
  registeredHash: "a".repeat(64),
  state: "ACTIVE",
  content: {
    policy: "recommend",
    device_flows: [
      {
        nickname: "Left cortex",
        device_template_path: "device-templates/pod8206hr.toml",
        sinks: [
          { sink_name: "disk", sink_type: "csv", sink_location: "C:/template" },
          { sink_name: "live", sink_type: "plot" },
        ],
      },
    ],
  },
};

const RESOLVED = [
  {
    flowIndex: 0,
    deviceConfigId: 17,
    sinks: [{ folder: "D:/runs/run-19", name: "left" }, {}],
  },
];

const startRunSource = readFileSync(new URL("./StartRunDialog.vue", import.meta.url), "utf8");

describe("sink destination composition", () => {
  it("takes the extension from the sink type, not from what was typed", () => {
    expect(composeSinkLocation("D:/runs", "left", "csv")).toBe("D:/runs/left.csv");
    // A name that already spells the extension is not doubled...
    expect(composeSinkLocation("D:/runs", "left.csv", "csv")).toBe("D:/runs/left.csv");
    // ...and one carrying the WRONG extension is corrected to the sink's own,
    // so a template's EDF sink can never be sent a path ending ".csv".
    expect(composeSinkLocation("D:/runs", "left.csv", "edf")).toBe("D:/runs/left.csv.edf");
  });

  it("joins with the separator the folder itself uses and trims a trailing one", () => {
    expect(composeSinkLocation("C:\\data\\runs", "left", "pvfs")).toBe("C:\\data\\runs\\left.pvfs");
    expect(composeSinkLocation("D:/runs/", "left", "csv")).toBe("D:/runs/left.csv");
  });

  it("returns nothing while either half is missing or the sink writes no file", () => {
    expect(composeSinkLocation("", "left", "csv")).toBe("");
    expect(composeSinkLocation("D:/runs", "", "csv")).toBe("");
    expect(composeSinkLocation("D:/runs", "live", "plot")).toBe("");
    expect(isFileSink("plot")).toBe(false);
    expect(isFileSink("csv")).toBe(true);
  });

  it("keeps a typed name from turning into a folder path", () => {
    expect(composeSinkLocation("D:/runs", "a/b", "csv")).toBe("D:/runs/a-b.csv");
  });
});

describe("compact template-run payload", () => {
  it("validates host output folders before issuing the atomic command", () => {
    expect(startRunSource).toContain("await validateOutputFolders(");
    expect(startRunSource).toContain("Boolean(folderValidationError.value)");
    expect(startRunSource).toContain("await verifyOutputFolders().catch(() => {})");
    expect(startRunSource.indexOf("await validateOutputFolders(")).toBeLessThan(
      startRunSource.indexOf("createTemplateRun(requestPayload"),
    );
    expect(startRunSource).not.toContain("Save as Draft");
    expect(startRunSource).not.toContain('value="draft"');
  });

  it("copies invisible template identity and sends only run-owned fields", () => {
    const payload = buildTemplateRunPayload({
      template: ACTIVE_TEMPLATE,
      assignments: RESOLVED,
      name: "  Cortical run 019  ",
      experimentId: "study-3",
      notes: "  second cohort  ",
    });

    expect(payload).toEqual({
      source_template_id: "tmpl-14",
      expected_template_hash: "a".repeat(64),
      assignments: [
        {
          flow_index: 0,
          device_config_id: 17,
          // Only the file sink gets a location. The backend rejects one on a
          // plot sink outright (session_config._locations_by_index).
          sink_locations: [{ sink_index: 0, sink_location: "D:/runs/run-19/left.csv" }],
        },
      ],
      name: "Cortical run 019",
      experiment_id: "study-3",
      notes: "second cohort",
      execution: { mode: "immediate" },
    });
    expect(payload).not.toHaveProperty("content");
    expect(payload).not.toHaveProperty("source_template_snapshot");
    expect(payload).not.toHaveProperty("policy");
    expect(payload).not.toHaveProperty("device_flows");
  });

  it("addresses each sink positionally, independent of the others", () => {
    const twoFileSinks = {
      ...ACTIVE_TEMPLATE,
      content: {
        ...ACTIVE_TEMPLATE.content,
        device_flows: [
          {
            ...ACTIVE_TEMPLATE.content.device_flows[0],
            sinks: [
              { sink_name: "disk", sink_type: "csv" },
              { sink_name: "live", sink_type: "plot" },
              { sink_name: "archive", sink_type: "edf" },
            ],
          },
        ],
      },
    };

    const payload = buildTemplateRunPayload({
      template: twoFileSinks,
      assignments: [
        {
          flowIndex: 0,
          deviceConfigId: 17,
          sinks: [
            { folder: "D:/fast", name: "left" },
            {},
            { folder: "E:/archive", name: "left-archive" },
          ],
        },
      ],
    });

    expect(payload.assignments[0].sink_locations).toEqual([
      { sink_index: 0, sink_location: "D:/fast/left.csv" },
      { sink_index: 2, sink_location: "E:/archive/left-archive.edf" },
    ]);
  });

  it("refuses a file sink with no resolvable destination", () => {
    // The backend has no "allocate this one for me" path on a template run:
    // every file sink in the snapshot must arrive with an explicit location.
    expect(() =>
      buildTemplateRunPayload({
        template: ACTIVE_TEMPLATE,
        assignments: [{ flowIndex: 0, deviceConfigId: 17, sinks: [{ folder: "", name: "left" }, {}] }],
      }),
    ).toThrow(/file sink needs an output folder/i);

    expect(() =>
      buildTemplateRunPayload({
        template: ACTIVE_TEMPLATE,
        assignments: [{ flowIndex: 0, deviceConfigId: 17, sinks: [] }],
      }),
    ).toThrow(/file sink needs an output folder/i);
  });

  it("rejects incomplete assignments and invalid schedules before create", () => {
    expect(() =>
      buildTemplateRunPayload({
        template: ACTIVE_TEMPLATE,
        assignments: [{ flowIndex: 0, deviceConfigId: null, sinks: RESOLVED[0].sinks }],
      }),
    ).toThrow(/device assignment/i);

    expect(() =>
      buildTemplateRunPayload({
        template: ACTIVE_TEMPLATE,
        assignments: RESOLVED,
        scheduleAt: "2020-01-01T00:00",
        now: new Date("2026-08-04T12:00:00Z"),
      }),
    ).toThrow(/future/i);
  });

  it("serializes a future schedule while fallback remains server-owned", () => {
    const payload = buildTemplateRunPayload({
      template: ACTIVE_TEMPLATE,
      assignments: RESOLVED,
      scheduleAt: "2026-08-05T09:30:00Z",
      now: new Date("2026-08-04T12:00:00Z"),
    });

    expect(payload.execution).toEqual({
      mode: "scheduled",
      start_at: "2026-08-05T09:30:00.000Z",
    });
  });
});

describe("template revision guard", () => {
  it("treats a state or registered-hash change as stale", () => {
    expect(templateRevisionChanged(ACTIVE_TEMPLATE, { ...ACTIVE_TEMPLATE })).toBe(false);
    expect(templateRevisionChanged(ACTIVE_TEMPLATE, { ...ACTIVE_TEMPLATE, state: "CHANGED" })).toBe(true);
    expect(
      templateRevisionChanged(ACTIVE_TEMPLATE, {
        ...ACTIVE_TEMPLATE,
        registeredHash: "b".repeat(64),
      }),
    ).toBe(true);
  });
});
