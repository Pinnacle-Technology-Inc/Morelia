import { describe, expect, it } from "vitest";
import { durationSecondsFromMinutes, sessionTiming, sessionStopExplanation, validateDurationSeconds } from "./session-timing";

const start = "2026-09-23T12:00:00Z";
const at = (seconds) => Date.parse(start) + seconds * 1000;
const run = { lifecycle: "Active", durationSeconds: 60, startedAt: start, endedAt: "2026-09-23T12:00:15Z" };

describe("recorded span and display countdown", () => {
  it("does not arm a duration before the first recorded sample", () => {
    expect(sessionTiming({ ...run, startedAt: null, endedAt: null }, at(120))).toEqual({
      timed: true, deadlineMs: null, recordedLabel: "Waiting for data",
      limitLabel: "0h 01m 00s", remainingLabel: "Waiting for data",
    });
  });

  it("keeps the recorded span fixed during an outage while remaining time decreases", () => {
    expect(sessionTiming(run, at(20))).toMatchObject({ recordedLabel: "0h 00m 15s", remainingLabel: "0h 00m 40s" });
    expect(sessionTiming({ ...run, health: "Recovering" }, at(45))).toMatchObject({
      recordedLabel: "0h 00m 15s", remainingLabel: "0h 00m 15s", deadlineMs: at(60),
    });
  });

  it("ignores replacement process start and restores the same deadline after reload", () => {
    const recovered = { ...run, runtimes: [{ started_at: "2026-09-23T12:00:50Z" }] };
    expect(sessionTiming(recovered, at(55)).remainingLabel).toBe("0h 00m 05s");
    expect(sessionTiming(JSON.parse(JSON.stringify(recovered)), at(56)).remainingLabel).toBe("0h 00m 04s");
  });

  it("clamps remaining time and never claims completion from elapsed time", () => {
    expect(sessionTiming(run, at(120))).toMatchObject({
      remainingLabel: "Duration reached; awaiting stop confirmation", recordedLabel: "0h 00m 15s",
    });
    expect(run.lifecycle).toBe("Active");
  });

  it("shows final drain samples beyond the limit and does not tick completed spans", () => {
    const completed = { ...run, lifecycle: "Completed", endedAt: "2026-09-23T12:01:04Z" };
    expect(sessionTiming(completed, at(90))).toMatchObject({ recordedLabel: "0h 01m 04s", remainingLabel: "Run ended" });
    expect(sessionTiming(completed, at(300)).recordedLabel).toBe("0h 01m 04s");
  });

  it("keeps unlimited timing and unknown legacy timing honest", () => {
    expect(sessionTiming({ ...run, durationSeconds: null }, at(90))).toMatchObject({
      timed: false, recordedLabel: "0h 00m 15s", remainingLabel: null, limitLabel: "Unlimited",
    });
    expect(sessionTiming({ lifecycle: "Completed", createdAt: start }, at(90))).toMatchObject({
      recordedLabel: "Recording timing unavailable", deadlineMs: null,
    });
  });

  it("preserves a real zero-length recording span and rejects reversed evidence", () => {
    expect(sessionTiming({ ...run, endedAt: start }).recordedLabel).toBe("0h 00m 00s");
    expect(sessionTiming({ ...run, endedAt: "2026-09-23T11:59:59Z" }).recordedLabel).toBe("Recording timing unavailable");
  });

  it("accepts storage boundaries and rejects minutes whose conversion overflows", () => {
    expect(validateDurationSeconds(2147483647)).toBe(2147483647);
    expect(durationSecondsFromMinutes(35791394)).toBe(2147483640);
    expect(() => durationSecondsFromMinutes(35791395)).toThrow();
  });
});

describe("stop explanation from operation evidence", () => {
  const stopped = { ...run, lifecycle: "Completed" };
  const stop = (reason, extra = {}) => ({ command: "stop", state: "succeeded", created_at: "2026-09-23T12:00:30Z",
    details: { stop_reason: reason }, ...extra });

  it("distinguishes early user stop, deadline stop and missing evidence", () => {
    expect(sessionStopExplanation(stopped, [stop("user_stop")])).toBe("Stopped by user before duration ended");
    expect(sessionStopExplanation(stopped, [stop("duration_ended")])).toBe("Requested duration ended");
    expect(sessionStopExplanation(stopped, [])).toBeNull();
  });

  it("explains a pre-start schedule cancellation without inventing samples", () => {
    expect(sessionStopExplanation({ lifecycle: "Completed", scheduledTime: "2026-09-23T13:00:00Z" }, [stop("user_stop")]))
      .toBe("Stopped by user before scheduled start");
  });

  it("preserves failed and forced results without calling them clean", () => {
    expect(sessionStopExplanation({ ...run, lifecycle: "Stopping" }, [stop("user_stop", { state: "uncertain" })]))
      .toContain("shutdown uncertain");
    expect(sessionStopExplanation(stopped, [stop("duration_ended", {
      details: { stop_reason: "duration_ended", shutdown_result: { forced_termination: true } },
    })])).toContain("unclean shutdown; output integrity is not confirmed");
  });

  it("does not infer session-wide completion from one teardown receipt", () => {
    const explanation = sessionStopExplanation(stopped, [stop("duration_ended", {
      state: "failed",
      details: { stop_reason: "duration_ended", teardown_confirmed: true, output_integrity_confirmed: false },
    })]);
    expect(explanation).toContain("Requested duration ended — shutdown failed");
    expect(explanation).toContain("output integrity is not confirmed");
    expect(explanation).not.toContain("completed with warnings");
  });

  it("explains a successful scheduled stop with recording warnings", () => {
    const explanation = sessionStopExplanation(stopped, [stop("duration_ended", {
      details: { stop_reason: "duration_ended", warnings: [
        { code: "unclean_shutdown", message: "Final recording samples could not be verified." },
      ] },
    })]);
    expect(explanation).toContain("Requested duration ended — completed with warnings");
    expect(explanation).toContain("Final recording samples could not be verified");
    expect(explanation).not.toContain("failed");
  });
});
