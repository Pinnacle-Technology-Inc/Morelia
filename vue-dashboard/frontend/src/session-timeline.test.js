import { describe, expect, it } from "vitest";
import {
  buildActivityTimeline,
  buildSessionTimeline,
  formatGapWindow,
  recentTimelineEntries,
  TimelineCategory,
} from "./session-timeline";

describe("buildActivityTimeline", () => {
  it("renders durable Activity records directly without reconstructing raw telemetry", () => {
    const entries = buildActivityTimeline([
      {
        activity_id: "activity-1",
        occurred_at: "2026-08-12T12:00:00Z",
        category: "issues",
        severity: "error",
        title: "Issue opened",
        summary: "Runtime heartbeat stale",
        details: { incident_id: "incident-1" },
      },
    ]);

    expect(entries).toEqual([{
      key: "activity:activity-1",
      at: "2026-08-12T12:00:00Z",
      category: TimelineCategory.SUPERVISION,
      tone: "bad",
      title: "Issue opened",
      summary: "Runtime heartbeat stale",
      details: { incident_id: "incident-1" },
    }]);
  });
});

describe("formatGapWindow", () => {
  it("formats timestamp boundaries instead of stringifying objects", () => {
    expect(formatGapWindow({
      gap_start: { timestamp: 1_700_000_000 },
      gap_end: { timestamp: 1_700_000_004.5 },
    })).toContain("4.5 seconds");
    expect(formatGapWindow({ gap_start: null, gap_end: null })).toBe("Boundaries not reported");
  });
});

describe("buildSessionTimeline", () => {
  it("turns repeated runtime reports into meaningful dataflow transitions", () => {
    const events = [
      report("1", "2026-08-12T10:00:00Z", "healthy"),
      report("2", "2026-08-12T10:01:00Z", "healthy"),
      report("3", "2026-08-12T10:02:00Z", "unhealthy"),
      report("4", "2026-08-12T10:03:00Z", "unhealthy"),
      report("5", "2026-08-12T10:04:00Z", "healthy"),
    ];

    const entries = buildSessionTimeline({ events });

    expect(entries.map((entry) => entry.title)).toEqual(["Data resumed", "Data disrupted"]);
    expect(entries.map((entry) => entry.at)).toEqual([
      "2026-08-12T10:04:00Z",
      "2026-08-12T10:02:00Z",
    ]);
    expect(entries.every((entry) => entry.category === TimelineCategory.DATAFLOW)).toBe(true);
    expect(entries[0].summary).toContain("device-1");
  });

  it("keeps sink delivery changes separate from source stream changes", () => {
    const events = [
      sinkReport("1", "2026-08-12T11:00:00Z", "healthy"),
      sinkReport("2", "2026-08-12T11:01:00Z", "failed", "Destination refused writes"),
      sinkReport("3", "2026-08-12T11:02:00Z", "healthy"),
    ];

    const entries = buildSessionTimeline({ events });

    expect(entries.map((entry) => entry.title)).toEqual(["Output resumed", "Output disrupted"]);
    expect(entries[1].summary).toContain("Destination refused writes");
  });

  it("merges durable gaps, incidents, and operations without duplicating command failures", () => {
    const entries = buildSessionTimeline({
      events: [{
        id: "event-9",
        type: "runtime.command_failed",
        data: {
          operation_id: "op-1",
          command: "stop",
          error_message: "Runtime did not answer",
          received_at: "2026-08-12T12:01:00Z",
        },
      }],
      gaps: [{
        gap_id: "gap-1",
        device_id: "device-1",
        reason: "automatic reconnect",
        confidence: "bounded",
        created_at: "2026-08-12T12:02:00Z",
      }],
      incidents: [
        {
          incident_id: "incident-data",
          axis: "data_path",
          reason: "stream unhealthy",
          opened_at: "2026-08-12T11:58:00Z",
          resolved_at: "2026-08-12T12:03:00Z",
          resolution: "stream recovered",
        },
        {
          incident_id: "incident-system",
          axis: "control_plane",
          reason: "watchdog heartbeat stale",
          opened_at: "2026-08-12T12:04:00Z",
        },
      ],
      operations: [{
        operation_id: "op-1",
        command: "stop",
        state: "failed",
        error_message: "Runtime did not answer",
        created_at: "2026-08-12T12:00:00Z",
        finished_at: "2026-08-12T12:01:00Z",
      }],
    });

    expect(entries.map((entry) => entry.title)).toEqual([
      "Supervision incident opened",
      "Dataflow incident resolved",
      "Data gap recorded",
      "Stop failed",
      "Dataflow incident opened",
    ]);
    expect(entries.filter((entry) => entry.title === "Stop failed")).toHaveLength(1);
    expect(entries[0].category).toBe(TimelineCategory.SUPERVISION);
    expect(entries[2].category).toBe(TimelineCategory.DATAFLOW);
  });
});

describe("recentTimelineEntries", () => {
  it("returns only the latest three meaningful entries by default", () => {
    const entries = Array.from({ length: 5 }, (_, index) => ({ key: String(index) }));

    expect(recentTimelineEntries(entries).map((entry) => entry.key)).toEqual(["0", "1", "2"]);
    expect(recentTimelineEntries(entries, 2)).toHaveLength(2);
    expect(recentTimelineEntries(entries, 0)).toEqual([]);
  });
});

function report(id, receivedAt, streamStatus) {
  return {
    id,
    type: "runtime.report",
    data: {
      received_at: receivedAt,
      sequence: Number(id),
      devices: [{ device_id: "device-1", stream_status: streamStatus }],
    },
  };
}

function sinkReport(id, receivedAt, health, message = null) {
  return {
    id,
    type: "runtime.report",
    data: {
      received_at: receivedAt,
      sequence: Number(id),
      devices: [{ device_id: "device-1", stream_status: "healthy" }],
      sinks: [{ sink_id: "sink-1", source_id: "device-1", health, message }],
    },
  };
}
