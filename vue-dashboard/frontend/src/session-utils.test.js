import { describe, expect, it } from "vitest";
import { sessions } from "./data";
import { countSessionsForTab, filterSessions, summarizeAttentionSessions } from "./session-utils";

describe("session filtering", () => {
  it("returns only sessions needing attention", () => {
    expect(filterSessions(sessions, "needs-attention").map((session) => session.id)).toEqual(["s002"]);
  });

  it("searches session names and experiment names case-insensitively", () => {
    expect(filterSessions(sessions, "active", "sleep").map((session) => session.id)).toEqual(["s002"]);
    expect(filterSessions(sessions, "active", "CORTICAL").map((session) => session.id)).toEqual(["s001"]);
  });

  it("keeps archived sessions out of completed counts", () => {
    expect(countSessionsForTab(sessions, "completed")).toBe(1);
    expect(countSessionsForTab(sessions, "archived")).toBe(1);
  });

  it("limits the overview attention summary while retaining the total count", () => {
    const attentionSessions = Array.from({ length: 5 }, (_, index) => ({
      id: `attention-${index}`,
      health: "Needs action",
    }));

    expect(summarizeAttentionSessions(attentionSessions)).toEqual({
      total: 5,
      visible: attentionSessions.slice(0, 3),
      hidden: 2,
    });
  });
});
