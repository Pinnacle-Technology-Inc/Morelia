import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { deriveFlowStatus } from "../session-flow-status";

const sessionDetailSource = readFileSync(new URL("./SessionDetailPage.vue", import.meta.url), "utf8");
const sessionsPageSource = readFileSync(new URL("./SessionsPage.vue", import.meta.url), "utf8");
const appSource = readFileSync(new URL("../App.vue", import.meta.url), "utf8");

describe("template-centric session closure", () => {
  it("routes session creation through templates instead of a blank session action", () => {
    expect(sessionsPageSource).not.toContain("new-session");
    expect(sessionsPageSource).not.toContain("New Session");
    expect(sessionsPageSource).toContain("open-templates");
    expect(appSource).toContain('@open-templates="changeTab(\'templates\')"');
  });

  it("never restarts a stopped session in place", () => {
    expect(sessionDetailSource).not.toContain("restartStopped");
    expect(sessionDetailSource).not.toContain("confirmRestart");
    expect(sessionDetailSource).not.toContain("dialog === 'restart'");
    expect(sessionDetailSource).not.toContain("Duplicate Session");
    expect(sessionDetailSource).toContain("Start another run");
    expect(sessionDetailSource).toContain("start-another-run");
  });

  it("does not expose Draft repair or delayed-start controls", () => {
    expect(sessionDetailSource).not.toContain("loadSinkPlan");
    expect(sessionDetailSource).not.toContain("updateSinkLocations");
    expect(sessionDetailSource).not.toContain("Edit output paths");
    expect(sessionDetailSource).not.toContain("startDraft");
    expect(sessionDetailSource).toContain("immutable run history");
  });

  it("shows command failures in a dismissible dialog instead of inline page chrome", () => {
    expect(sessionDetailSource).toContain("CommandErrorDialog");
    expect(sessionDetailSource).toContain('@close="dismissCommandError"');
    expect(sessionDetailSource).not.toContain('v-if="commandError" class="sink-repair-feedback"');
  });

  it("gates another run on the current source while retaining frozen provenance", () => {
    expect(sessionDetailSource).toContain("canRunTemplate");
    expect(sessionDetailSource).toContain("loadSessionTemplate");
    expect(sessionDetailSource).toContain("templateStateHint");
    expect(sessionDetailSource).toContain("source_template_id");
    expect(sessionDetailSource).toContain("source_template_snapshot");
    expect(sessionDetailSource).toContain("canonical_hash_version");
  });

  it("keeps stop and active recovery controls available", () => {
    expect(sessionDetailSource).toContain("stopSession(props.sessionId)");
    expect(sessionDetailSource).toContain("Recover Stream");
    expect(sessionDetailSource).toContain("Approve Recovery");
    expect(sessionDetailSource).toContain("Retry Recovery");
  });

  it("describes stopped sessions as closed runs, not restartable sessions", () => {
    const status = deriveFlowStatus({ lifecycle: "Stopped" });

    expect(status.reason).toContain("source template");
    expect(status.reason).not.toContain("restart");
  });
});
