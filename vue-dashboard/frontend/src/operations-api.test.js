import { describe, expect, it } from "vitest";
import { getBlockingOperation } from "./operations-api";

describe("operation API helpers", () => {
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
