import { describe, expect, it } from "vitest";
import { canSubmitResolution } from "../operations-api";

describe("operations resolution contract", () => {
  it("does not allow a resolution without an explicit outcome", () => {
    expect(canSubmitResolution({ outcome: "", resolvedBy: "operator", resolutionNote: "verified" })).toBe(false);
  });
});
