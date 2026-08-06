import { describe, expect, it } from "vitest";
import {
  buildSinkLocationUpdates,
  hasOccupiedSink,
  hasUnreadySink,
  isRecoverableSinkProblem,
  moveOutputToFolder,
  outputFolder,
  suggestedSinkLocation,
  validateOutputFolders,
} from "./sink-location-recovery";

describe("sink-location recovery", () => {
  it.each(["sink_location_exists", "sink_parent_unavailable"])(
    "recognizes %s as an actionable start failure",
    (code) => {
      expect(isRecoverableSinkProblem({ problem: { code } })).toBe(true);
    },
  );

  it("does not turn unrelated start failures into output repair", () => {
    expect(isRecoverableSinkProblem({ problem: { code: "device_claim_conflict" } })).toBe(false);
  });

  it("finds an occupied explicit output during preflight", () => {
    expect(hasOccupiedSink({ sinks: [{ occupied: false }, { occupied: true }] })).toBe(true);
    expect(hasOccupiedSink({ sinks: [] })).toBe(false);
  });

  it("finds an unusable parent during preflight", () => {
    expect(hasUnreadySink({ sinks: [{ parent_issue: null }, { parent_issue: "missing" }] })).toBe(true);
    expect(hasUnreadySink({ sinks: [{ parent_issue: null }] })).toBe(false);
  });

  it("only offers a server suggestion when its parent was verified and it preserves the output type", () => {
    const sink = {
      occupied: true,
      parent_issue: null,
      sink_type: "edf",
      current_location: "C:/runs/taken.edf",
      suggested_location: "C:/runs/taken-1.edf",
    };
    expect(suggestedSinkLocation(sink)).toBe("C:/runs/taken-1.edf");
    expect(suggestedSinkLocation({
      ...sink,
      suggested_location: "C:\\runs\\taken-1.edf",
    })).toBe("C:\\runs\\taken-1.edf");
    expect(suggestedSinkLocation({ ...sink, parent_issue: "not_writable" })).toBe("");
    expect(suggestedSinkLocation({ ...sink, suggested_location: "C:/runs/taken-1.csv" })).toBe("");
    expect(suggestedSinkLocation({ ...sink, suggested_location: "D:/other/taken-1.edf" })).toBe("");
  });

  it("verifies every distinct output folder against the host before create", async () => {
    const visited = [];
    await validateOutputFolders(["C:/runs", "C:/runs", "D:/archive"], async (folder) => {
      visited.push(folder);
      return { path: folder, exists: true, writable: true };
    });
    expect(visited).toEqual(["C:/runs", "D:/archive"]);
  });

  it.each([
    [{ exists: false, writable: false }, /does not exist/i],
    [{ exists: true, writable: false }, /not writable/i],
  ])("blocks an invalid host output folder", async (listing, message) => {
    await expect(validateOutputFolders(["Z:/bad"], async () => ({ path: "Z:/bad", ...listing })))
      .rejects.toThrow(message);
  });

  it("turns an unresolved host path into an actionable validation error", async () => {
    await expect(validateOutputFolders(["Z:/gone"], async () => {
      throw new Error("network drive disconnected");
    })).rejects.toThrow(/could not be resolved/i);
  });

  it("builds the positional PATCH payload from edited sink rows", () => {
    expect(buildSinkLocationUpdates([
      { flow_index: 2, sink_index: 1, edited_location: "  C:/runs/new.edf  " },
    ])).toEqual([
      { flow_index: 2, sink_index: 1, sink_location: "C:/runs/new.edf" },
    ]);
  });

  it("refuses to save a blank output path", () => {
    expect(() => buildSinkLocationUpdates([
      { flow_index: 0, sink_index: 0, edited_location: "  " },
    ])).toThrow(/output path is required/i);
  });

  it.each([
    ["C:\\old\\run.edf", "D:\\approved", "D:\\approved\\run.edf"],
    ["C:\\old\\run.edf", "D:\\", "D:\\run.edf"],
    ["/old/run.csv", "/approved/outputs/", "/approved/outputs/run.csv"],
    ["/old/run.csv", "/", "/run.csv"],
  ])("moves %s into a chosen host folder", (location, folder, expected) => {
    expect(moveOutputToFolder(location, folder)).toBe(expected);
  });

  it.each([
    ["C:\\old\\run.edf", "C:\\old"],
    ["C:\\run.edf", "C:\\"],
    ["/old/run.csv", "/old"],
    ["/run.csv", "/"],
  ])("opens the folder picker beside %s", (location, expected) => {
    expect(outputFolder(location)).toBe(expected);
  });
});
