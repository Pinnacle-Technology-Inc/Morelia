import { ApiProblem, requestJson } from "./api-client";

export { ApiProblem };

export async function listOperations({ state } = {}) {
  const params = new URLSearchParams();
  if (state) params.set("state", state);
  const suffix = params.toString() ? `?${params}` : "";
  return requestJson(`/api/v1/operations/${suffix}`);
}

export async function resolveOperation(operationId, { outcome, resolvedBy, resolutionNote }) {
  return requestJson(`/api/v1/operations/${operationId}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      outcome,
      resolved_by: resolvedBy,
      resolution_note: resolutionNote,
    }),
  });
}

export function canSubmitResolution({ outcome, resolvedBy, resolutionNote }) {
  return Boolean(outcome && resolvedBy?.trim() && resolutionNote?.trim());
}

export function getBlockingOperation(problem) {
  if (!problem || problem.code !== "operation_blocked_by_uncertain") return null;
  return {
    operationId: problem.operation_id,
    dataflowId: problem.dataflow_id,
    scope: problem.scope,
    targetDeviceId: problem.target_device_id,
    command: problem.command,
    state: problem.operation_state,
    resolutionRequired: problem.resolution_required === true,
  };
}
