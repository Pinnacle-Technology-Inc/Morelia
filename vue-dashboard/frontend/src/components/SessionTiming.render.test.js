import { createSSRApp } from "vue";
import { renderToString } from "@vue/server-renderer";
import { expect, it } from "vitest";
import ActiveSessionCard from "./ActiveSessionCard.vue";
import SessionDetailPage from "../pages/SessionDetailPage.vue";

const session = { id: "7", name: "Recorded session", lifecycle: "Active", health: "Healthy",
  durationSeconds: 60, startedAt: "2026-09-23T12:00:02Z", endedAt: "2026-09-23T12:00:15Z", deviceFlows: [],
  recordingBounds: [{ source_id: "source", sink_id: "csv",
    first_sample_at: "2026-09-23T12:00:00Z", last_sample_at: "2026-09-23T12:00:15Z" }] };

it("renders sample span on the real active card without runtime ownership timestamps", async () => {
  const html = await renderToString(createSSRApp(ActiveSessionCard, { session }));
  expect(html).toContain("Recorded span");
  expect(html).toContain("0h 00m 15s");
  expect(html).toContain("Time remaining");
});

it("renders waiting-for-data on the real active card before recording", async () => {
  const html = await renderToString(createSSRApp(ActiveSessionCard, { session: { ...session, startedAt: null, endedAt: null, recordingBounds: [] } }));
  expect(html).toContain("Waiting for data");
  expect(html).not.toContain("0h 00m 15s");
});

it("renders sample bounds and the duration limit on the real detail page", async () => {
  const html = await renderToString(createSSRApp(SessionDetailPage, { session, sessionId: session.id }));
  expect(html).toContain("Recorded span");
  expect(html).toContain("0h 00m 15s");
  expect(html).toContain("Duration limit");
  expect(html).toContain("0h 01m 00s");
  expect(html).toContain("First recorded sample");
  expect(html).toContain("Session started");
  expect(html).toContain("Last confirmed sample");
});

it("offers Stop for a pending scheduled run", async () => {
  const html = await renderToString(createSSRApp(SessionDetailPage, {
    session: { ...session, lifecycle: "Scheduled", startedAt: null, endedAt: null, durationSeconds: null }, sessionId: session.id,
  }));
  expect(html).toContain("Stop this session cleanly");
});
