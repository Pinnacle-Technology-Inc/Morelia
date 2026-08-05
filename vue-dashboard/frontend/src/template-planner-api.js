import { requestJson } from "./api-client";

/** Keep path separators so Flask ``<path:reference>`` can match local catalog refs. */
export function encodeTemplateReference(reference) {
  return String(reference)
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

export async function loadAssignmentPlan(templateReference) {
  if (!templateReference) throw new TypeError("A session template is required.");
  const value = await requestJson(
    `/api/v1/session-templates/${encodeTemplateReference(templateReference)}/assignment-plan`,
    { method: "POST" },
  );
  if (!value || typeof value !== "object" || !Array.isArray(value.assignments) || !Array.isArray(value.unresolved_requirements)) {
    throw new TypeError("The assignment planner returned an unexpected response shape.");
  }
  return value;
}

export function deviceTypeForFlow(plan, flowIndex) {
  const assignment = plan?.assignments?.find((item) => item.flow_index === flowIndex);
  const unresolved = plan?.unresolved_requirements?.find((item) => item.flow_index === flowIndex);
  return assignment?.device_type ?? unresolved?.device_type ?? null;
}

// An operator may choose among compatible hardware, but a stream must never
// show a device type the template cannot configure. Existing selections in the
// same run are also unavailable to prevent one device being assigned twice.
export function compatiblePoolDevicesForFlow(devices, { flowIndex, assignments, deviceType }) {
  const takenElsewhere = new Set(
    assignments
      .filter((assignment) => assignment.flowIndex !== flowIndex)
      .map((assignment) => assignment.deviceConfigId)
      .filter((id) => id != null),
  );
  return devices.filter(
    (device) =>
      device.availability === "available" &&
      device.status !== "claimed" &&
      !takenElsewhere.has(device.id) &&
      (!deviceType || device.type === deviceType),
  );
}
