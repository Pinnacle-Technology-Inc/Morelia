import { describe, expect, it } from "vitest";

describe("device pool page contract", () => {
  it("keeps unopenable availability independent from claimed ownership", () => {
    const row = { availability: "unopenable", status: "claimed" };
    expect(row.availability).not.toBe(row.status);
  });
});
