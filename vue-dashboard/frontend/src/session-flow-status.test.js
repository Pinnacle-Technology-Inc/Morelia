import { describe, expect, it } from "vitest";
import {
  deriveFlowStatus,
  deriveRatState,
  deriveStreamRows,
  FlowTone,
  formatReportAge,
  isOutboxUnproven,
  worstTone,
} from "./session-flow-status";

describe("worstTone", () => {
  it("keeps the more severe of two tones regardless of argument order", () => {
    expect(worstTone(FlowTone.GOOD, FlowTone.BAD)).toBe(FlowTone.BAD);
    expect(worstTone(FlowTone.BAD, FlowTone.GOOD)).toBe(FlowTone.BAD);
    expect(worstTone(FlowTone.WARN, FlowTone.GOOD)).toBe(FlowTone.WARN);
    expect(worstTone(FlowTone.IDLE, FlowTone.IDLE)).toBe(FlowTone.IDLE);
  });
});

describe("deriveFlowStatus — resting lifecycles", () => {
  it("never animates or alarms for a session that is not running", () => {
    for (const lifecycle of ["Preparing", "Scheduled", "Stopped", "Completed"]) {
      const status = deriveFlowStatus({ lifecycle, health: "Unknown" });
      expect(status.tone).toBe(FlowTone.IDLE);
      expect(status.flowing).toBe(false);
    }
  });

  it("reports the pre-answer deep-link state as loading, not as a stopped session", () => {
    const status = deriveFlowStatus({ lifecycle: "Unknown" });
    expect(status.tone).toBe(FlowTone.IDLE);
    expect(status.headline).toBe("Loading status…");
  });

  it("ignores a bad health value while a run is preparing", () => {
    const status = deriveFlowStatus({ lifecycle: "Preparing", health: "Needs action" });
    expect(status.tone).toBe(FlowTone.IDLE);
  });
});

describe("deriveFlowStatus — running lifecycles", () => {
  it("is green and flowing while active and healthy on a live stream", () => {
    const status = deriveFlowStatus({
      lifecycle: "Active",
      health: "Healthy",
      activityState: "live",
    });
    expect(status.tone).toBe(FlowTone.GOOD);
    expect(status.flowing).toBe(true);
    expect(status.headline).toBe("Streaming");
  });

  it("animates while starting, before health has stabilized", () => {
    const status = deriveFlowStatus({
      lifecycle: "Starting",
      health: "Unknown",
      activityState: "connecting",
    });
    expect(status.tone).toBe(FlowTone.WARN);
    expect(status.flowing).toBe(true);
    expect(status.headline).toBe("Starting up");
  });

  it("does not let a healthy report override a Starting lifecycle into green", () => {
    // Health has not stabilized during a transition, so it gets no vote yet.
    const status = deriveFlowStatus({
      lifecycle: "Starting",
      health: "Healthy",
      activityState: "live",
    });
    expect(status.tone).toBe(FlowTone.WARN);
  });

  it("goes red and STOPS animating when a stream needs action", () => {
    const status = deriveFlowStatus({
      lifecycle: "Active",
      health: "Needs action",
      activityState: "live",
    });
    expect(status.tone).toBe(FlowTone.BAD);
    // An animated red bar reads as "still working" and would hide the stall.
    expect(status.flowing).toBe(false);
  });

  it("keeps animating through recovery — work is in flight", () => {
    const status = deriveFlowStatus({
      lifecycle: "Active",
      health: "Recovering",
      activityState: "live",
    });
    expect(status.tone).toBe(FlowTone.WARN);
    expect(status.flowing).toBe(true);
  });

  it("degrades a healthy session to amber when our own event stream drops", () => {
    const status = deriveFlowStatus({
      lifecycle: "Active",
      health: "Healthy",
      activityState: "unavailable",
    });
    // Amber, never red: a dead SSE connection means we cannot SEE the session,
    // not that the session failed. Red here would train operators to ignore red.
    expect(status.tone).toBe(FlowTone.WARN);
    expect(status.reason).toMatch(/out of date/);
  });

  it("surfaces phase and health in the reason line", () => {
    const status = deriveFlowStatus({
      lifecycle: "Active",
      health: "Healthy",
      phase: "streaming",
      activityState: "live",
    });
    expect(status.reason).toContain("streaming");
    expect(status.reason).toContain("Healthy");
  });

  it("notes a failed detail refresh without blanking the tone", () => {
    const status = deriveFlowStatus({
      lifecycle: "Active",
      health: "Healthy",
      activityState: "live",
      detailAvailable: false,
    });
    expect(status.tone).toBe(FlowTone.WARN);
    expect(status.reason).toMatch(/could not be refreshed/);
  });

  it("does not claim to be waiting for a first report once a rail exists", () => {
    // The healthiest possible case leaves every note branch unpushed, so the
    // old bare `|| "Waiting for the first status report…"` fallback fired
    // precisely when a report HAD just arrived — printed directly beneath the
    // bar's own "report 0s ago" clock.
    const status = deriveFlowStatus({
      lifecycle: "Active",
      health: "Healthy",
      activityState: "live",
      streams: [{ id: "a", label: "pod-a", tone: FlowTone.GOOD, flowing: true }],
    });
    expect(status.reason).not.toMatch(/Waiting for the first/);
    expect(status.reason).toBe("All streams are reporting healthy.");
  });

  it("names the single troubled stream in the reason line", () => {
    const status = deriveFlowStatus({
      lifecycle: "Active",
      health: "Healthy",
      activityState: "live",
      streams: [
        { id: "a", label: "pod-a", tone: FlowTone.GOOD, flowing: true },
        { id: "b", label: "pod-b", tone: FlowTone.BAD, flowing: false, reason: "Port not connected" },
      ],
    });
    expect(status.reason).toBe("pod-b: Port not connected.");
  });

  it("still waits on the first report when nothing has reported at all", () => {
    const status = deriveFlowStatus({
      lifecycle: "Active",
      health: "Healthy",
      activityState: "live",
      streams: [],
    });
    // No rail: `Stream health` covers it, and the waiting copy stays reachable
    // for a session that genuinely has not reported.
    expect(deriveFlowStatus({ lifecycle: "Ending", activityState: "live" }).reason).toMatch(
      /Waiting for the first/,
    );
    expect(status.reason).toContain("Healthy");
  });
});

describe("deriveRatState", () => {
  // The rat renders in Session Summary while the rail renders in Stream Health.
  // They are different cards reading the same verdict, so this mapping is the
  // seam where a running rat could end up beside a red rail.
  const status = (tone, flowing) => ({ tone, flowing });

  it("runs only when the session is green and moving", () => {
    expect(deriveRatState(status(FlowTone.GOOD, true))).toBe("running");
  });

  it("stops dead on a red session, however the flow flag reads", () => {
    expect(deriveRatState(status(FlowTone.BAD, false))).toBe("stopped");
    expect(deriveRatState(status(FlowTone.BAD, true))).toBe("stopped");
  });

  it("rests rather than alarms while the session is idle", () => {
    expect(deriveRatState(status(FlowTone.IDLE, false))).toBe("paused");
  });

  it("uses the suspect gait when a row is literally Suspect", () => {
    // Suspect has its own frame set, so it must outrank the generic amber walk.
    expect(deriveRatState(status(FlowTone.WARN, true), [{ status: "Suspect" }])).toBe("suspect");
  });

  it("recovers on amber when nothing is specifically suspect", () => {
    expect(deriveRatState(status(FlowTone.WARN, true), [{ status: "Healthy" }])).toBe("recovering");
  });

  it("holds still on amber that is not flowing", () => {
    expect(deriveRatState(status(FlowTone.WARN, false), [{ status: "Healthy" }])).toBe("stopped");
  });

  it("agrees with deriveFlowStatus end to end", () => {
    const rows = deriveStreamRows({ devices: [{ device_id: "a", stream_status: "unhealthy" }] });
    const flow = deriveFlowStatus({ lifecycle: "Active", health: "Healthy", streams: rows });
    // A green session-level rollup must not talk the rat into running when the
    // rail below it is red.
    expect(flow.tone).toBe(FlowTone.BAD);
    expect(deriveRatState(flow, rows)).toBe("stopped");
  });
});

const device = (overrides = {}) => ({
  device_id: "pod-a",
  stream_status: "healthy",
  action: null,
  reason: null,
  recovery_stage: null,
  recovery_attempt: null,
  pending_recovery: false,
  ...overrides,
});

const sink = (overrides = {}) => ({
  source_id: "pod-a",
  sink_id: "csv-1",
  health: "healthy",
  status: "current",
  sample_loss: 0,
  ...overrides,
});

describe("deriveStreamRows — the per-stream axis", () => {
  it("marches a healthy stream and holds every other state still", () => {
    const rows = deriveStreamRows({
      devices: [
        device({ device_id: "a", stream_status: "healthy" }),
        device({ device_id: "b", stream_status: "suspect" }),
        device({ device_id: "c", stream_status: "unhealthy" }),
      ],
    });
    expect(rows.map((row) => row.tone)).toEqual([FlowTone.GOOD, FlowTone.WARN, FlowTone.BAD]);
    // Amber-frozen: anything less than healthy stops moving, because an amber
    // track that keeps marching reads as "recovering, don't worry".
    expect(rows.map((row) => row.flowing)).toEqual([true, false, false]);
  });

  it("does not fold suspect into healthy — the bug this rail exists to undo", () => {
    const [row] = deriveStreamRows({ devices: [device({ stream_status: "suspect" })] });
    expect(row.tone).toBe(FlowTone.WARN);
    expect(row.status).toBe("Suspect");
  });

  it("keeps the two port-wait cases apart", () => {
    const [absent] = deriveStreamRows({
      devices: [device({ stream_status: "suspect", action: "waiting_for_port" })],
    });
    const [held] = deriveStreamRows({
      devices: [device({ stream_status: "suspect", action: "waiting_for_port_release" })],
    });
    expect(absent.reason).toMatch(/not connected/);
    expect(held.reason).toMatch(/held/);
    expect(absent.reason).not.toBe(held.reason);
  });

  it("reads the port-wait copy from action, not from the pending_recovery boolean", () => {
    // pending_recovery collapses both port cases into one bit; the copy has to
    // come from the field that still tells them apart.
    const [row] = deriveStreamRows({
      devices: [
        device({ stream_status: "suspect", pending_recovery: true, recovery_stage: "retry_wait" }),
      ],
    });
    expect(row.reason).toMatch(/Retrying/);
  });

  it("colours the row for a failing sink but keeps the stream track marching", () => {
    // The device is producing fine — it is the write path that is losing data.
    // Merging these would make an unplugged pod and a full disk look identical.
    const [row] = deriveStreamRows({
      devices: [device({ stream_status: "healthy" })],
      sinks: [sink({ health: "failed" })],
    });
    expect(row.tone).toBe(FlowTone.BAD);
    expect(row.flowing).toBe(true);
    expect(row.sinkTone).toBe(FlowTone.BAD);
  });

  it("surfaces durable sample loss even while the sink reports healthy", () => {
    const [row] = deriveStreamRows({
      devices: [device()],
      sinks: [sink({ health: "healthy", sample_loss: 1240 })],
    });
    expect(row.sinkTone).toBe(FlowTone.WARN);
    expect(row.sinkNote).toContain("1,240");
  });

  it("does not warn about a sink the newest report simply did not mention", () => {
    // The runtime lists a sink in its report ONLY when that sink has errored
    // (Morelia._drain_sink_errors), so the backend necessarily marks every
    // working sink `stale` with a null health. Treating that as unproven pinned
    // every healthy row to amber and printed "1 not in latest report" under a
    // green session, forever.
    const [row] = deriveStreamRows({
      devices: [device()],
      sinks: [sink({ health: null, status: "stale" })],
    });
    expect(row.sinkTone).toBe(FlowTone.GOOD);
    expect(row.tone).toBe(FlowTone.GOOD);
    expect(row.sinkNote).toBe("No sink errors reported");
  });

  it("still warns when a live sink snapshot could not be read at all", () => {
    // `unknown` is the backend's parse-FAILURE marker — a snapshot arrived and
    // was malformed. That is a real blind spot, unlike plain absence.
    const [row] = deriveStreamRows({
      devices: [device()],
      sinks: [sink({ health: null, status: "unknown" })],
    });
    expect(row.sinkTone).toBe(FlowTone.WARN);
    expect(row.sinkNote).toMatch(/unreadable/);
  });

  it("still surfaces durable loss on a sink the report never mentioned", () => {
    // Loss comes from output_files and outlives the report, so it must survive
    // the absence rule above.
    const [row] = deriveStreamRows({
      devices: [device()],
      sinks: [sink({ health: null, status: "stale", sample_loss: 12 })],
    });
    expect(row.sinkTone).toBe(FlowTone.WARN);
    expect(row.sinkNote).toContain("12 samples lost");
  });

  it("only attributes sinks to the source that owns them", () => {
    const rows = deriveStreamRows({
      devices: [device({ device_id: "a" }), device({ device_id: "b" })],
      sinks: [sink({ source_id: "a" }), sink({ source_id: "b", health: "failed" })],
    });
    expect(rows[0].tone).toBe(FlowTone.GOOD);
    expect(rows[1].tone).toBe(FlowTone.BAD);
  });

  it("freezes and de-greens every row once the runtime goes quiet", () => {
    const rows = deriveStreamRows({
      devices: [device({ stream_status: "healthy" })],
      unproven: true,
    });
    expect(rows[0].flowing).toBe(false);
    expect(rows[0].tone).toBe(FlowTone.WARN);
    expect(rows[0].unproven).toBe(true);
  });

  it("labels rows from the configured flow, matching by identity before position", () => {
    const rows = deriveStreamRows({
      devices: [device({ device_id: "b" }), device({ device_id: "a" })],
      configuredFlows: [
        { nickname: "a", hardware_id: "HW-A" },
        { nickname: "b", hardware_id: "HW-B" },
      ],
    });
    // Report order differs from config order — matching by position would put
    // HW-A on device b.
    expect(rows[0].hardwareId).toBe("HW-B");
    expect(rows[1].hardwareId).toBe("HW-A");
  });

  it("tolerates a report with no devices", () => {
    expect(deriveStreamRows()).toEqual([]);
  });
});

describe("deriveFlowStatus — with a rail", () => {
  it("counts flowing streams in the headline", () => {
    const streams = deriveStreamRows({
      devices: [
        device({ device_id: "a", stream_status: "healthy" }),
        device({ device_id: "b", stream_status: "suspect", action: "waiting_for_port" }),
        device({ device_id: "c", stream_status: "healthy" }),
      ],
    });
    const status = deriveFlowStatus({
      lifecycle: "Active",
      health: "Healthy",
      activityState: "live",
      streams,
    });
    expect(status.headline).toBe("2 of 3 streams flowing");
  });

  it("lets one unhealthy stream outvote a green session-level rollup", () => {
    // This is the whole point: `health` says Healthy because the backend rollup
    // is lossy, and the raw stream state says otherwise.
    const streams = deriveStreamRows({ devices: [device({ stream_status: "unhealthy" })] });
    const status = deriveFlowStatus({
      lifecycle: "Active",
      health: "Healthy",
      activityState: "live",
      streams,
    });
    expect(status.tone).toBe(FlowTone.BAD);
  });

  it("never reads green while the runtime has stopped reporting", () => {
    const status = deriveFlowStatus({
      lifecycle: "Active",
      health: "Healthy",
      activityState: "live",
      streams: deriveStreamRows({ devices: [device()], unproven: true }),
      outboxHealth: "stale",
    });
    expect(status.tone).toBe(FlowTone.WARN);
    expect(status.unproven).toBe(true);
    expect(status.headline).toMatch(/unproven/);
    expect(status.reason).toMatch(/stopped reporting/);
  });

  it("keeps a genuinely failed stream red rather than softening it to stale-amber", () => {
    // Staleness is a floor, not a ceiling.
    const status = deriveFlowStatus({
      lifecycle: "Active",
      health: "Healthy",
      streams: deriveStreamRows({
        devices: [device({ stream_status: "unhealthy" })],
        unproven: true,
      }),
      outboxHealth: "stale",
    });
    expect(status.tone).toBe(FlowTone.BAD);
  });

  it("keeps the transition headline while starting, rail or not", () => {
    const status = deriveFlowStatus({
      lifecycle: "Starting",
      streams: deriveStreamRows({ devices: [device()] }),
    });
    expect(status.headline).toBe("Starting up");
  });
});

describe("report freshness", () => {
  it("classifies only stale and overflow as unproven", () => {
    expect(isOutboxUnproven("stale")).toBe(true);
    expect(isOutboxUnproven("overflow")).toBe(true);
    expect(isOutboxUnproven("fresh")).toBe(false);
    expect(isOutboxUnproven(null)).toBe(false);
  });

  it("formats an age that an operator can read at a glance", () => {
    const now = Date.parse("2026-07-24T12:00:00Z");
    expect(formatReportAge("2026-07-24T11:59:58Z", now)).toBe("2s ago");
    expect(formatReportAge("2026-07-24T11:56:00Z", now)).toBe("4m ago");
    expect(formatReportAge("2026-07-24T09:00:00Z", now)).toBe("3h ago");
  });

  it("returns null rather than a fake age when nothing has been reported", () => {
    expect(formatReportAge(null)).toBeNull();
    expect(formatReportAge("not-a-date")).toBeNull();
  });
});
