import { createSSRApp } from "vue";
import { renderToString } from "@vue/server-renderer";
import { expect, it, vi } from "vitest";
import DevicesPage from "./DevicesPage.vue";

const fixture = vi.hoisted(() => ({ snapshot: null }));
// Controller behavior is exercised separately. Feed a snapshot at setup time
// to inspect the real page/child templates without a browser or live hardware.
vi.mock("../device-scan", () => ({
  createDeviceScanController: ({ onUpdate }) => {
    onUpdate(fixture.snapshot);
    return { refresh() {}, dispose() {} };
  },
}));

function snapshot(probeState) {
  return { scanId: "visible-scan", scannedAt: "2026-09-28T16:00:00Z", warnings: [],
    scanState: probeState === "complete" ? "complete" : "probing", total: 1,
    completed: probeState === "complete" ? 1 : 0,
    devices: [{ id: "serial", scanKey: "device:SERIAL", hardwareId: "SERIAL", port: "COM1", name: "Attached POD",
      type: probeState === "complete" ? "pod8401hr" : "unknown",
      availability: probeState === "complete" ? "available" : "unverified",
      probeState, status: "unconfigured", endpoints: [] }] };
}

it.each([["queued", "Waiting"], ["probing", "Checking"]])("renders %s inventory while the scan is unfinished", async (state, label) => {
  fixture.snapshot = snapshot(state);
  const html = await renderToString(createSSRApp(DevicesPage));
  expect(html).toContain("Checked 0 of 1 devices");
  expect(html).toContain("Attached POD");
  expect(html).toContain(label);
  expect(html).not.toContain("Not found");
  expect(html).toContain('aria-disabled="true"');
});

it("renders completed rows without a pending label", async () => {
  fixture.snapshot = snapshot("complete");
  const html = await renderToString(createSSRApp(DevicesPage));
  expect(html).toContain("pod8401hr");
  expect(html).not.toContain("Checking");
  expect(html).toContain('aria-disabled="false"');
});

it("renders a completed failed probe as unavailable", async () => {
  fixture.snapshot = snapshot("complete");
  fixture.snapshot.devices[0].availability = "unavailable";
  const html = await renderToString(createSSRApp(DevicesPage));
  expect(html).toContain("Unavailable");
  expect(html).not.toContain("Unverified");
  expect(html).not.toContain("Checking");
});
