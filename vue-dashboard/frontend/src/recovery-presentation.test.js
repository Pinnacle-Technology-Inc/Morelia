import { describe, expect, it } from "vitest";
import { deriveRecoveryPresentation } from "./recovery-presentation";

const live = { lifecycle: "Active", telemetryCurrent: true };
const present = (stage, progress = {}, device = {}, diagnostic = {}, context = live) =>
  deriveRecoveryPresentation({
    recovery_state: "recovering", recovery_attempt: 2, recovery_attempt_max: 3,
    recovery_progress: { stage, ...progress }, ...device,
  }, diagnostic, context);

describe("reported recovery progress", () => {
  it.each([
    ["detected", "Disruption detected"],
    ["settling", "Allowing the connection to settle"],
    ["stopping_stream", "Stopping the affected stream"],
    ["checking_presence", "Checking device presence"],
    ["waiting_for_device", "Waiting for the device"],
    ["presence_check_failed", "Presence check failed"],
    ["checking_port", "Checking port access"],
    ["waiting_for_port", "Waiting for port access"],
    ["restarting_stream", "Restarting the stream"],
    ["waiting_for_ping", "Waiting for PING"],
    ["waiting_for_data", "Waiting for fresh data"],
    ["recovery_verified", "Recovery verified"],
    ["streaming", "Streaming"],
    ["awaiting_approval", "Waiting for approval"],
    ["cleanup_failed", "Stream cleanup failed"],
    ["port_access_timeout", "Port access timed out"],
    ["attempts_exhausted", "Recovery attempts exhausted"],
    ["restart_failed", "Stream restart failed"],
    ["retrying", "Waiting to retry"],
    ["check_failed", "Recovery check failed"],
  ])("names the %s step", (stage, title) => {
    expect(present(stage)).toMatchObject({ title, heading: "Current step", attempt: "2 of 3" });
  });

  it("keeps recovered streams visible after the operational recovery state returns to idle", () => {
    expect(present("streaming", { verification: "data" }, { recovery_state: "idle" }))
      .toMatchObject({ visible: true, tone: "good", data: "Fresh data confirmed" });
    expect(deriveRecoveryPresentation({ recovery_state: "idle" }, {}, live).visible).toBe(false);
  });

  it("separates a successful PING from data arrival", () => {
    expect(present("recovery_verified", { ping_status: "passed", verification: "ping" }))
      .toMatchObject({ ping: "Passed", verification: "PING", data: "Fresh data not confirmed" });
  });

  it("shows data verification when PING failed", () => {
    expect(present("recovery_verified", { ping_status: "failed", verification: "data" }))
      .toMatchObject({ ping: "Failed", verification: "Fresh data", data: "Fresh data confirmed" });
  });

  it("retains only reported history with epoch timestamps and attempt numbers", () => {
    const result = present("waiting_for_data", {
      started_at: 1792768800,
      history: [
        { stage: "restarting_stream", at: 1792768795, attempt: 2 },
        { stage: "waiting_for_data", at: 1792768800, attempt: 2 },
      ],
    });
    expect(result.history.map((step) => step.label)).toEqual(["Restarting the stream", "Waiting for fresh data"]);
    expect(result.history[0].at).toContain("2026");
    expect(result.history[0].at).toContain("CDT");
    expect(result.history[0].attempt).toBe(2);
    expect(result.startedAt).toBe(result.history[1].at);
    expect(present("waiting_for_data").history).toEqual([]);
  });

  it("bounds history and does not invent dates for missing timestamps", () => {
    const history = Array.from({ length: 20 }, () => ({ stage: "checking_presence" }));
    const result = present("checking_presence", { history });
    expect(result.history).toHaveLength(16);
    expect(result.history[0].at).toBeNull();
  });

  it.each(["Stopping", "Completed", "Cancelled", "Starting", "Unknown"])("labels %s evidence as historical", (lifecycle) => {
    const result = present("waiting_for_data", {}, {}, {}, { lifecycle, telemetryCurrent: true });
    expect(result).toMatchObject({ current: false, heading: "Last reported step", tone: "muted" });
    expect(result.explanation).not.toContain("is waiting");
  });

  it("does not claim streaming on stale telemetry", () => {
    const result = present("streaming", { verification: "data" }, {}, {}, { lifecycle: "Active", telemetryCurrent: false });
    expect(result).toMatchObject({ current: false, heading: "Last reported step", tone: "muted" });
    expect(result.explanation).toContain("does not describe current device activity");
  });

  it("does not guess future protocol stages", () => {
    expect(present("future_stage")).toMatchObject({ title: "Recovery status unavailable", visible: true });
  });
});

describe("older recovery reports", () => {
  it("does not invent a presence check after the stream stopped", () => {
    const result = deriveRecoveryPresentation({ action: "stopped_stream_waiting_for_reconnect" }, {}, live);
    expect(result.title).toBe("Stream stopped; awaiting recovery check");
    expect(result.explanation).toContain("next recovery check has not been reported");
  });

  it("explains the session 61 presence-check exception without claiming absence", () => {
    const result = deriveRecoveryPresentation({
      recovery_state: "recovering", action: "port_check_failed", hardware_present: null,
      recovery_attempt: 1, recovery_attempt_max: 3,
    }, { failure: { last_error: "[Errno 13] Permission denied" } }, live);
    expect(result).toMatchObject({
      title: "Presence check failed", presence: "Presence check failed; unknown",
      lastError: "[Errno 13] Permission denied", history: [], hasProgress: false,
    });
  });

  it("explains waiting_for_heartbeat as a failed PING followed by data verification", () => {
    const result = deriveRecoveryPresentation({
      recovery_state: "recovering", action: "waiting_for_heartbeat", hardware_present: true,
    }, { failure: { last_error: "PING timed out" }, heartbeat: { status: "missing", packet_count: 0 } }, live);
    expect(result).toMatchObject({ title: "Waiting for fresh data", ping: "Failed", data: "Fresh data not confirmed" });
    expect(result.explanation).toContain("PING failed after the restart");
    expect(result.lastError).toBe("PING timed out");
  });

  it.each([
    ["waiting_for_port", "Waiting for the device"],
    ["waiting_for_port_release", "Waiting for port access"],
  ])("distinguishes legacy %s", (action, title) => {
    expect(deriveRecoveryPresentation({ action, recovery_state: "recovering" }, {}, live).title).toBe(title);
  });

  it.each([
    ["cleanup_failed", "Stream cleanup failed"],
    ["port_release_timeout", "Port access timed out"],
  ])("does not label %s as exhausted attempts", (reason, title) => {
    const result = deriveRecoveryPresentation({ recovery_state: "exhausted", reason, action: "needs_action" }, {}, live);
    expect(result.title).toBe(title);
    expect(result.explanation).not.toContain("retry budget");
  });

  it("requires actual sample evidence to claim data proof on old reports", () => {
    expect(deriveRecoveryPresentation({ recovery_state: "recovered", stream_status: "healthy" }, {}, live).data)
      .toBe("Fresh data not confirmed");
    expect(deriveRecoveryPresentation({ recovery_state: "recovered", stream_status: "healthy" }, {
      heartbeat: { status: "fresh", packet_count: 128 },
    }, live).data).toBe("Fresh data confirmed");
  });
});
