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
