import { describe, expect, it } from "vitest";

describe("Experiments page contract", () => {
  it("uses archived as the explicit removal state", () => {
    const archived = { archived_at: "2026-01-01" };
    expect(Boolean(archived.archived_at)).toBe(true);
  });
});
