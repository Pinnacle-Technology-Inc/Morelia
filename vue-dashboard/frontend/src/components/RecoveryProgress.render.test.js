import { createSSRApp } from "vue";
import { renderToString } from "@vue/server-renderer";
import { expect, it } from "vitest";
import RecoveryProgress from "./RecoveryProgress.vue";
import { deriveRecoveryPresentation } from "../recovery-presentation";

const live = { lifecycle: "Active", telemetryCurrent: true };
const render = (status) => renderToString(createSSRApp(RecoveryProgress, { status }));

it("shows the current step, failed PING, data proof, error, and real step history", async () => {
  const html = await render(deriveRecoveryPresentation({
    hardware_present: true, recovery_attempt: 2, recovery_attempt_max: 3,
    recovery_progress: {
      stage: "waiting_for_data", ping_status: "failed", verification: null,
      last_error: "PING timed out", history: [{ stage: "waiting_for_data", at: 1792768800, attempt: 2 }],
    },
  }, {}, live));
  for (const text of ["Current step", "Waiting for fresh data", "2 of 3", "Present", "PING", "Failed",
    "Fresh data not confirmed", "PING timed out", "Recent reported steps (1)", "CDT"]) {
    expect(html).toContain(text);
  }
  expect(html).not.toContain("Stopping the affected stream");
});

it("labels a closed session's final streaming state as last reported", async () => {
  const html = await render(deriveRecoveryPresentation({
    recovery_progress: { stage: "streaming", verification: "data" },
  }, {}, { lifecycle: "Completed", telemetryCurrent: true }));
  expect(html).toContain("Last reported step");
  expect(html).toContain("Session closed");
  expect(html).not.toContain("Current step");
  expect(html).toContain("recovery-progress--muted");
});

it("renders an older check exception with unknown presence and no invented history", async () => {
  const html = await render(deriveRecoveryPresentation({ action: "port_check_failed", hardware_present: null }, {
    failure: { last_error: "<device read failed>" },
  }, live));
  expect(html).toContain("Presence check failed; unknown");
  expect(html).toContain("&lt;device read failed&gt;");
  expect(html).toContain("Step history was not included");
  expect(html).not.toContain("Presence not checked");
});
