import { describe, expect, it } from "vitest";
import { canSubmitResolution, getBlockingOperation, resolveOperation } from "./operations-api";

describe("operation API helpers", () => {
  it("submits an explicit terminal outcome", async () => {
    globalThis.fetch = async (_url, options) => ({ ok: true, json: async () => JSON.parse(options.body) });
    await expect(resolveOperation("op-1", {
      outcome: "succeeded",
      resolvedBy: "operator",
      resolutionNote: "verified",
    })).resolves.toMatchObject({ outcome: "succeeded", resolved_by: "operator" });
  });

  it("requires outcome, resolver, and note before submit", () => {
    expect(canSubmitResolution({ outcome: "", resolvedBy: "operator", resolutionNote: "note" })).toBe(false);
    expect(canSubmitResolution({ outcome: "failed", resolvedBy: "operator", resolutionNote: "note" })).toBe(true);
  });
  it("extracts blocking uncertain operation details from problem responses", () => {
    expect(getBlockingOperation({
      code: "operation_blocked_by_uncertain",
      operation_id: "op-1",
      dataflow_id: "df-1",
      scope: "dataflow",
      target_device_id: null,
      command: "start",
      operation_state: "uncertain",
      resolution_required: true,
    })).toEqual({
      operationId: "op-1",
      dataflowId: "df-1",
      scope: "dataflow",
      targetDeviceId: null,
      command: "start",
      state: "uncertain",
      resolutionRequired: true,
    });
  });

  it("ignores non-operation problem responses", () => {
    expect(getBlockingOperation({ code: "command_in_flight" })).toBeNull();
  });
});
