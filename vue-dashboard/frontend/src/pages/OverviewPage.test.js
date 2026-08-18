import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const overviewSource = readFileSync(new URL("./OverviewPage.vue", import.meta.url), "utf8");
const appSource = readFileSync(new URL("../App.vue", import.meta.url), "utf8");

describe("overview recent incident history", () => {
  it("loads bounded global incident history instead of rendering the contract placeholder", () => {
    expect(overviewSource).toContain('import { loadIncidents } from "../history-api"');
    expect(overviewSource).toContain("loadIncidents({ pageSize: RECENT_INCIDENT_LIMIT })");
    expect(overviewSource).not.toContain(
      "Recent incidents and recoveries are unavailable until the live history contract is wired.",
    );
  });

  it("renders the defined incident summary columns and opens related history or sessions", () => {
    for (const heading of ["Time", "Session", "Stream", "Reason", "Outcome"]) {
      expect(overviewSource).toContain(`<th>${heading}</th>`);
    }
    expect(overviewSource).toContain('v-for="incident in recentIncidents"');
    expect(overviewSource).toContain("@click=\"$emit('open-session', String(incident.session_id))\"");
    expect(overviewSource).toContain("@click.stop=\"$emit('open-session', String(incident.session_id))\"");
    expect(overviewSource).toContain("@click=\"$emit('view-history')\"");
    expect(appSource).toContain('@view-history="changeTab(\'incidents\')"');
  });
});
