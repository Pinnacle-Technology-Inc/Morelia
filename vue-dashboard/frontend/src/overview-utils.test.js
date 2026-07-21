import { describe, expect, it } from "vitest";
import {
  getSessionDeviceFlows,
  getVisibleActiveSessions,
  loadOverviewPreferences,
  moveSessionByOffset,
  reconcileActiveSessionOrder,
  reorderSessionIds,
  saveOverviewPreferences,
  sortSessionsOldestFirst,
} from "./overview-utils";

const activeSessions = [
  { id: "newest", startTime: "2026-06-19T08:00:00" },
  { id: "oldest", startTime: "2026-06-19T04:00:00" },
  { id: "middle", startTime: "2026-06-19T06:00:00" },
];

describe("overview active-session organization", () => {
  it("orders active sessions by oldest start time by default", () => {
    expect(sortSessionsOldestFirst(activeSessions).map((session) => session.id)).toEqual([
      "oldest",
      "middle",
      "newest",
    ]);
  });

  it("preserves saved order and appends newly active sessions by oldest start time", () => {
    expect(reconcileActiveSessionOrder(activeSessions, ["newest", "oldest", "inactive"])).toEqual([
      "newest",
      "oldest",
      "middle",
    ]);
  });

  it("moves a dragged session before or after a target session", () => {
    expect(reorderSessionIds(["a", "b", "c", "d"], "d", "b", "before")).toEqual([
      "a",
      "d",
      "b",
      "c",
    ]);
    expect(reorderSessionIds(["a", "b", "c", "d"], "a", "c", "after")).toEqual([
      "b",
      "c",
      "a",
      "d",
    ]);
  });

  it("supports keyboard reordering without moving beyond list boundaries", () => {
    expect(moveSessionByOffset(["a", "b", "c"], "b", -1)).toEqual(["b", "a", "c"]);
    expect(moveSessionByOffset(["a", "b", "c"], "a", -1)).toEqual(["a", "b", "c"]);
  });

  it("limits active sessions until the user chooses to show all", () => {
    const sessions = Array.from({ length: 6 }, (_, index) => ({ id: `s00${index}` }));

    expect(getVisibleActiveSessions(sessions, false, 4)).toEqual(sessions.slice(0, 4));
    expect(getVisibleActiveSessions(sessions, true, 4)).toEqual(sessions);
  });

  it("returns only device flows assigned to the requested session", () => {
    const flows = [
      { id: "flow-a", sessionId: "s001" },
      { id: "flow-b", sessionId: "s002" },
      { id: "flow-c", sessionId: "s001" },
    ];

    expect(getSessionDeviceFlows(flows, "s001").map((flow) => flow.id)).toEqual([
      "flow-a",
      "flow-c",
    ]);
  });

  it("loads and saves persisted overview preferences", () => {
    const values = new Map();
    const storage = {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
    };
    const preferences = {
      orderedSessionIds: ["s002", "s001"],
      expandedSessionIds: ["s002"],
      showAllActiveSessions: true,
      isSidebarCollapsed: true,
      collapsedSidebarSections: ["scheduled"],
    };

    expect(saveOverviewPreferences(storage, "overview", preferences)).toBe(true);
    expect(loadOverviewPreferences(storage, "overview")).toEqual(preferences);
  });

  it("falls back to safe defaults when persisted preferences are invalid", () => {
    const storage = {
      getItem: () => "{not-json",
    };

    expect(loadOverviewPreferences(storage, "overview")).toEqual({
      orderedSessionIds: [],
      expandedSessionIds: [],
      showAllActiveSessions: false,
      isSidebarCollapsed: false,
      collapsedSidebarSections: [],
    });
  });
});
