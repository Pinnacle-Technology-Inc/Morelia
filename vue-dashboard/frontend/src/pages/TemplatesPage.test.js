import { describe, expect, it } from "vitest";
import {
  TEMPLATE_STATES,
  canRunTemplate,
  duplicateTemplateFrom,
  normalizeTemplate,
  templateControls,
  templateFlowSummary,
} from "../templates-api";

// The server's own allowed_actions vocabulary, per catalog state. These are the
// values the backend derives; the portal must render these and nothing else.
const SERVER_ALLOWED = {
  DISCOVERED: ["register"],
  PENDING: [],
  ACTIVE: ["archive"],
  DUPLICATE: [],
  AMBIGUOUS_RENAME: [],
  CHANGED: ["accept_change", "archive"],
  ARCHIVED: [],
  MISSING: ["resolve_rename"],
  INVALID: [],
};

function resource(state, overrides = {}) {
  return {
    template_id: state === "DISCOVERED" || state === "INVALID" ? null : "tmpl-1",
    name: "bench",
    reference: "bench.toml",
    registered_hash: "a".repeat(64),
    observed_hash: state === "CHANGED" ? "b".repeat(64) : "a".repeat(64),
    state,
    allowed_actions: SERVER_ALLOWED[state],
    warnings: [],
    content: { policy: "recommend", device_flows: [] },
    ...overrides,
  };
}

describe("template state and action matrix", () => {
  it.each(TEMPLATE_STATES)("renders only server-permitted actions for %s", (state) => {
    const template = normalizeTemplate(resource(state));
    const actionIds = templateControls(template)
      .filter((control) => control.kind === "action")
      .map((control) => control.id);

    expect(actionIds).toEqual(SERVER_ALLOWED[state]);
  });

  it.each(TEMPLATE_STATES)("only ACTIVE can reach run creation from %s", (state) => {
    const template = normalizeTemplate(resource(state));
    const hasRun = templateControls(template).some((control) => control.id === "run");

    expect(canRunTemplate(template)).toBe(state === "ACTIVE");
    expect(hasRun).toBe(state === "ACTIVE");
  });

  it("gives a DISCOVERED row an action it can actually complete", () => {
    // Regression: every server action used to route to the detail page keyed by
    // template_id, but DISCOVERED — the only state offering `register` — has no
    // id yet, so the one clickable control in a fresh catalog navigated to a
    // detail route with a null id and rendered an empty page. Register has to
    // run from the row against its flat reference, then navigate to the id the
    // server mints.
    const discovered = normalizeTemplate(resource("DISCOVERED"));
    const controls = templateControls(discovered);

    expect(discovered.templateId).toBeNull();
    expect(discovered.reference).toBe("bench.toml");
    expect(controls.map((control) => control.id)).toEqual(["register"]);
    expect(controls.every((control) => control.kind === "action")).toBe(true);
  });

  it("opens by internal id, never by filename", () => {
    const template = normalizeTemplate(resource("ACTIVE"));
    expect(templateControls(template).some((control) => control.id === "open")).toBe(true);
    expect(template.templateId).toBe("tmpl-1");

    // A discovered file has no identity yet, so there is nothing to open.
    const discovered = normalizeTemplate(resource("DISCOVERED"));
    expect(templateControls(discovered).some((control) => control.id === "open")).toBe(false);
  });

  it("points a duplicate at the original it copies", () => {
    const template = normalizeTemplate(
      resource("DUPLICATE", { duplicate_of_template_id: "tmpl-original" }),
    );
    const original = templateControls(template).find((control) => control.id === "open_original");

    expect(original).toBeTruthy();
    expect(template.duplicateOfTemplateId).toBe("tmpl-original");
    expect(canRunTemplate(template)).toBe(false);
  });

  it("drops an action the server did not offer, even if the client knows the name", () => {
    // Defence against a stale client deciding a transition is legal.
    const template = normalizeTemplate(resource("ARCHIVED", { allowed_actions: ["accept_change"] }));
    expect(template.allowedActions).toEqual(["accept_change"]);

    const invented = normalizeTemplate(resource("ARCHIVED", { allowed_actions: ["launch_now"] }));
    expect(invented.allowedActions).toEqual([]);
    expect(templateControls(invented).filter((c) => c.kind === "action")).toEqual([]);
  });

  it("rejects a state the contract does not define instead of guessing a rendering", () => {
    expect(() => normalizeTemplate(resource("SOMETHING_NEW"))).toThrow(/unknown state/);
    expect(() => normalizeTemplate(null)).toThrow(/unexpected response shape/);
  });
});

describe("accept-as-new-revision wording", () => {
  it("never implies the portal rewrote the TOML file", () => {
    const template = normalizeTemplate(resource("CHANGED"));
    const accept = templateControls(template).find((control) => control.id === "accept_change");

    expect(accept.label).toBe("Accept as new revision");
    expect(accept.confirm).toMatch(/new revision/i);
    expect(accept.confirm).toMatch(/ACTIVE/);
    // Both surfaces must say outright that the file is untouched. Asserting the
    // explicit denial is the durable check; forbidding the word "rewritten"
    // would fail on the very sentence that denies it.
    expect(accept.confirm).toMatch(/not modified/i);
    expect(accept.title).toMatch(/not rewritten/i);
  });
});

describe("catalog row columns", () => {
  it("counts streams and sinks across every flow", () => {
    const template = normalizeTemplate(
      resource("ACTIVE", {
        content: {
          policy: "recommend",
          device_flows: [
            { sinks: [{ sink_type: "csv" }, { sink_type: "plot" }] },
            { sinks: [{ sink_type: "csv" }] },
          ],
        },
      }),
    );

    expect(templateFlowSummary(template)).toEqual({ streams: 2, sinks: 3 });
  });

  it("reports 0 / 0 for a template whose content could not be read", () => {
    // INVALID parses to no content at all. The row still has to render, and a
    // template with nothing readable configures nothing — that is not a crash.
    const template = normalizeTemplate(resource("INVALID", { content: null }));

    expect(templateFlowSummary(template)).toEqual({ streams: 0, sinks: 0 });
    expect(templateFlowSummary(undefined)).toEqual({ streams: 0, sinks: 0 });
  });

  it("keeps a never-started template distinct from an uncounted one", () => {
    // The catalog route counts runs; the others omit the field. Collapsing both
    // to 0 would tell the operator a template has no runs on a page that never
    // asked, so `null` survives normalization and renders as an em dash.
    const counted = normalizeTemplate(resource("ACTIVE", { run_count: 0, latest_session: null }));
    const uncounted = normalizeTemplate(resource("ACTIVE"));

    expect(counted.runCount).toBe(0);
    expect(uncounted.runCount).toBeNull();
  });

  it("carries the newest run through for the latest-session column", () => {
    const latest = { id: 18, name: "Run 18", status: "active", created_at: "2026-08-04T12:00:00Z" };
    const template = normalizeTemplate(resource("ACTIVE", { run_count: 18, latest_session: latest }));

    expect(template.runCount).toBe(18);
    expect(template.latestSession).toEqual(latest);
  });
});

describe("duplicate import", () => {
  it("extracts the existing template a 409 points at", () => {
    const existing = { template_id: "tmpl-1", name: "bench", reference: "bench.toml" };
    const error = { problem: { code: "duplicate_template", existing_template: existing } };

    expect(duplicateTemplateFrom(error)).toEqual(existing);
  });

  it("ignores conflicts that are not duplicates", () => {
    expect(duplicateTemplateFrom({ problem: { code: "template_state_conflict" } })).toBeNull();
    expect(duplicateTemplateFrom(new Error("network"))).toBeNull();
  });
});
