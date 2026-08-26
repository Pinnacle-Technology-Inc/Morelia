import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const sidebarSource = readFileSync(new URL("./OverviewSidebar.vue", import.meta.url), "utf8");

describe("overview attention cards", () => {
  it("does not render empty incident context from a partial overview payload", () => {
    expect(sidebarSource).toContain('v-if="session.attentionReason"');
    expect(sidebarSource).toContain('v-if="session.attentionSince"');
  });
});
