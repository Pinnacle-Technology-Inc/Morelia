import { describe, expect, it } from "vitest";
import {
  countSessionsForTab,
  filterSessions,
  isRunningLifecycle,
  normalizeSession,
  operationOutcome,
  resolveSessionHealth,
  summarizeAttentionSessions,
} from "./session-utils";

const sessions = [
  { id: "s001", name: "Cortical Array Session 07", lifecycle: "Active", health: "Healthy", experiment: "Motor Learning Study", archived: false },
  { id: "s002", name: "Striatal LFP Recording", lifecycle: "Active", health: "Needs action", experiment: "Sleep Stage Analysis", archived: false },
  { id: "s005", name: "Auditory Evoked Potentials", lifecycle: "Completed", health: "Healthy", experiment: "Sleep Stage Analysis", archived: false },
  { id: "s006", name: "Prefrontal Sync - Archive", lifecycle: "Completed", health: "Healthy", experiment: "Motor Learning Study", archived: true },
];

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

  it("keeps stopped restartable without treating it as running", () => {
    expect(isRunningLifecycle("Active")).toBe(true);
    expect(isRunningLifecycle("Stopped")).toBe(false);
  });

  it("keeps completed sessions in completed filtering only", () => {
    const completed = { id: "done", lifecycle: "Completed", health: "Not running", archived: false };
    expect(filterSessions([completed], "completed")).toEqual([completed]);
    expect(filterSessions([completed], "active")).toEqual([]);
  });

  it("routes every split fault label into the needs-attention tab", () => {
    const faults = ["Delayed", "Unreachable", "Failed", "Not streaming", "Needs action"];
    for (const health of faults) {
      expect(filterSessions([{ id: "x", name: "x", lifecycle: "Active", health }], "needs-attention"))
        .toHaveLength(1);
    }
  });

  it("keeps a session we merely cannot see out of needs-attention", () => {
    const blind = { id: "x", name: "x", lifecycle: "Active", health: "Not reporting" };
    expect(filterSessions([blind], "needs-attention")).toEqual([]);
  });
});

describe("session health resolution", () => {
  it("reports a resting state rather than Unknown when nothing is running", () => {
    for (const lifecycle of ["Preparing", "Scheduled", "Stopped", "Completed"]) {
      // Health is absent for these because there is nothing to measure, not
      // because we lost track of the session.
      expect(resolveSessionHealth(null, lifecycle)).toBe("Not running");
    }
  });

  it("ignores a stale health value on a session that is not running", () => {
    expect(resolveSessionHealth("healthy", "Completed")).toBe("Not running");
  });

  it("says the session is not reporting when a running one has no live health", () => {
    expect(resolveSessionHealth(null, "Active")).toBe("Not reporting");
    expect(resolveSessionHealth("unknown", "Starting")).toBe("Not reporting");
  });

  it("keeps the three fault kinds distinct instead of collapsing them", () => {
    expect(resolveSessionHealth("delayed", "Active")).toBe("Delayed");
    expect(resolveSessionHealth("unreachable", "Active")).toBe("Unreachable");
    expect(resolveSessionHealth("failed", "Active")).toBe("Failed");
  });

  it("distinguishes a dataflow that stopped under a running session", () => {
    // HealthState.STOPPED while the plane still intends Active is a real
    // disagreement — it must not render as the Stopped lifecycle.
    expect(resolveSessionHealth("stopped", "Active")).toBe("Not streaming");
    expect(resolveSessionHealth(null, "Stopped")).toBe("Not running");
  });
});

it("preserves authoritative sample timestamps and legacy nulls", () => {
  expect(normalizeSession({ id: 1, status: "active", duration_seconds: 60,
    started_at: "2026-09-23T12:00:00Z", ended_at: "2026-09-23T12:00:15Z",
  })).toMatchObject({ durationSeconds: 60, startedAt: "2026-09-23T12:00:00Z", endedAt: "2026-09-23T12:00:15Z" });
  expect(normalizeSession({ id: 2, status: "completed", created_at: "2026-01-01T00:00:00Z" }))
    .toMatchObject({ durationSeconds: null, startedAt: null, endedAt: null });
});

describe("stop outcome presentation", () => {
  it("shows successful stops with and without explicit warnings", () => {
    expect(operationOutcome({ command: "stop", state: "succeeded" }))
      .toMatchObject({ label: "Completed", tone: "good", completed: true });
    expect(operationOutcome({ command: "stop", state: "succeeded", details: {
      warnings: [{ code: "unclean_shutdown", message: "Recording quality could not be confirmed." }],
    } })).toMatchObject({ label: "Completed with warnings", tone: "warn" });
  });

  it.each(["failed", "uncertain"])("does not reinterpret %s from one owner's teardown receipt", (state) => {
    const operation = { command: "stop", state, details: {
      teardown_confirmed: true, output_integrity_confirmed: false,
    } };
    expect(operationOutcome(operation)).toMatchObject({
      state, tone: "bad", completed: false,
    });
    expect(operation.state).toBe(state);
    expect(operation.details.output_integrity_confirmed).toBe(false);
    expect(operationOutcome({ ...operation, details: { ...operation.details, output_integrity_confirmed: true } }))
      .toMatchObject({ state, tone: "bad", completed: false });
  });

  it.each(["failed", "uncertain"])("preserves %s without proof the session stopped", (state) => {
    expect(operationOutcome({ command: "stop", state, details: { teardown_confirmed: false } }))
      .toMatchObject({ state, tone: "bad", completed: false });
  });

  it("does not reinterpret failures of other commands", () => {
    expect(operationOutcome({ command: "start", state: "failed", details: {
      teardown_confirmed: true, output_integrity_confirmed: false,
    } })).toMatchObject({ state: "failed", label: "Failed", tone: "bad", completed: false, warnings: [] });
  });
});
