import { afterEach, expect, it, vi } from "vitest";
import { encodeTemplateReference, loadAssignmentPlan } from "./template-planner-api";

afterEach(() => vi.restoreAllMocks());

it("posts the template identity and preserves planner outcomes", async () => {
  vi.stubGlobal("fetch", vi.fn(async (_url, options) => ({ ok: true, json: async () => ({ assignments: [], unresolved_requirements: [], warnings: [], complete: false, method: options.method }) })));
  await expect(loadAssignmentPlan("template/a")).resolves.toMatchObject({ complete: false });
});

it("keeps catalog path separators so local drafts reach the planner", async () => {
  const fetchMock = vi.fn(async () => ({
    ok: true,
    json: async () => ({ assignments: [], unresolved_requirements: [], warnings: [], complete: false }),
  }));
  vi.stubGlobal("fetch", fetchMock);

  expect(encodeTemplateReference("session-templates/folder-draft.toml")).toBe(
    "session-templates/folder-draft.toml",
  );
  await loadAssignmentPlan("session-templates/folder-draft.toml");
  expect(fetchMock.mock.calls[0][0]).toBe(
    "/api/v1/session-templates/session-templates/folder-draft.toml/assignment-plan",
  );
});
