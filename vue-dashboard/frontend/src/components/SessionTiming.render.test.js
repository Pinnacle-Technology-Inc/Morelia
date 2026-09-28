import { createSSRApp } from "vue";
import { renderToString } from "@vue/server-renderer";
import { expect, it } from "vitest";
import ActiveSessionCard from "./ActiveSessionCard.vue";

const session = { id: "7", name: "Recorded session", lifecycle: "Active", health: "Healthy",
  durationSeconds: 60, startedAt: "2026-09-23T12:00:00Z", endedAt: "2026-09-23T12:00:15Z", deviceFlows: [] };

it("renders sample span on the real active card without runtime ownership timestamps", async () => {
  const html = await renderToString(createSSRApp(ActiveSessionCard, { session }));
  expect(html).toContain("Recorded span");
  expect(html).toContain("0h 00m 15s");
  expect(html).toContain("Time remaining");
});

it("renders waiting-for-data on the real active card before recording", async () => {
  const html = await renderToString(createSSRApp(ActiveSessionCard, { session: { ...session, startedAt: null, endedAt: null } }));
  expect(html).toContain("Waiting for data");
  expect(html).not.toContain("0h 00m 15s");
});
