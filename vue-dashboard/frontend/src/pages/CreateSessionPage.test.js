import { describe, expect, it } from "vitest";

describe("create session planner states", () => {
  it("blocks start for incomplete planner results while retaining draft work", () => {
    const plan = { complete: false, unresolved_requirements: [{ flow_index: 0 }] };
    expect(plan.complete).toBe(false);
    expect(plan.unresolved_requirements).toHaveLength(1);
  });

  it("binds the template picker to catalog references, not stored-only names", () => {
    const catalog = [
      { source: "stored", name: "bench", reference: "bench", content: { policy: "recommend" } },
      { source: "local", name: "bench", reference: "session-templates/bench.toml", content: { policy: "automate" } },
      { source: "local", name: "broken", reference: "session-templates/broken.toml", content: null },
    ];
    const options = catalog.filter((template) => template.content != null);
    expect(options.map((template) => template.reference)).toEqual([
      "bench",
      "session-templates/bench.toml",
    ]);
    expect(options.map((template) => (template.source === "local" ? `${template.name} (draft)` : template.name))).toEqual([
      "bench",
      "bench (draft)",
    ]);
  });
});
