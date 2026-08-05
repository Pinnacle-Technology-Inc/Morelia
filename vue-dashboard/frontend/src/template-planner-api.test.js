import { afterEach, expect, it, vi } from "vitest";
import {
  compatiblePoolDevicesForFlow,
  deviceTypeForFlow,
  encodeTemplateReference,
  loadAssignmentPlan,
} from "./template-planner-api";

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

it("keeps a stream picker to its required device type and available untaken hardware", () => {
  const plan = {
    assignments: [{ flow_index: 0, device_type: "pod8206hr" }],
    unresolved_requirements: [
      { flow_index: 1, device_type: "pod8401hr" },
      { flow_index: 2, device_type: "pod8401hr" },
    ],
  };
  const assignments = [
    { flowIndex: 0, deviceConfigId: null },
    { flowIndex: 1, deviceConfigId: 14 },
  ];
  const devices = [
    { id: 11, type: "pod8206hr", status: "free", availability: "available" },
    { id: "pod8206hr:new", type: "pod8206hr", status: "unconfigured", availability: "available" },
    { id: 14, type: "pod8401hr", status: "free", availability: "available" },
    { id: 17, type: "pod8401hr", status: "claimed", availability: "available" },
  ];

  expect(deviceTypeForFlow(plan, 0)).toBe("pod8206hr");
  expect(deviceTypeForFlow(plan, 1)).toBe("pod8401hr");
  expect(compatiblePoolDevicesForFlow(devices, { flowIndex: 0, assignments, deviceType: "pod8206hr" }))
    .toMatchObject([{ id: 11 }, { id: "pod8206hr:new" }]);
  expect(compatiblePoolDevicesForFlow(devices, { flowIndex: 2, assignments, deviceType: "pod8401hr" }))
    .toEqual([]);
});
