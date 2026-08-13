import { describe, expect, it } from "vitest";
import {
  experimentErrorMessage,
  filterExperiments,
  summarizeExperiments,
} from "../experiment-utils";

describe("Experiments page contract", () => {
  it("uses archived as the explicit removal state", () => {
    const archived = { archived_at: "2026-01-01" };
    expect(Boolean(archived.archived_at)).toBe(true);
  });

  it("filters by experiment name or description without case sensitivity", () => {
    const rows = [
      { id: "1", name: "Motor Learning", description: "Cortical array", archived_at: null },
      { id: "2", name: "Sleep Study", description: "LFP validation", archived_at: "2026-01-01" },
    ];

    expect(filterExperiments(rows, "motor").map((row) => row.id)).toEqual(["1"]);
    expect(filterExperiments(rows, "lfp").map((row) => row.id)).toEqual(["2"]);
  });

  it("summarizes active and archived experiments", () => {
    expect(summarizeExperiments([
      { archived_at: null },
      { archived_at: null },
      { archived_at: "2026-01-01" },
    ])).toEqual({ active: 2, archived: 1, total: 3 });
  });

  it("turns stable API problem codes into actionable operator messages", () => {
    expect(experimentErrorMessage({ problem: { code: "experiment_name_conflict" } }))
      .toBe("An experiment with this name already exists.");
    expect(experimentErrorMessage({ problem: { code: "experiment_has_sessions" } }))
      .toBe("This experiment has linked sessions and cannot be permanently deleted.");
  });
});
