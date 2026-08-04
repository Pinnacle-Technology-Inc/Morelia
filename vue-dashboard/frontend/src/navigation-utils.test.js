import { describe, expect, it } from "vitest";
import { parseHash, toHash } from "./navigation-utils";

const TEMPLATE_ID = "5375636d26ee4fc48085eef25077a498";

describe("hash navigation", () => {
  it("parses top-level dashboard tabs", () => {
    expect(parseHash("#sessions")).toEqual({
      tab: "sessions", sessionId: null, templateId: null, templateView: null,
    });
    expect(parseHash("#devices")).toEqual({
      tab: "devices", sessionId: null, templateId: null, templateView: null,
    });
    expect(parseHash("#templates")).toEqual({
      tab: "templates", sessionId: null, templateId: null, templateView: null,
    });
    expect(parseHash("#operations")).toEqual({
      tab: "operations", sessionId: null, templateId: null, templateView: null,
    });
  });

  it("parses session detail", () => {
    expect(parseHash("#session/s002")).toEqual({
      tab: "sessions", sessionId: "s002", templateId: null, templateView: null,
    });
  });

  it("parses every template route", () => {
    expect(parseHash("#template/new")).toEqual({
      tab: "templates", sessionId: null, templateId: null, templateView: "new",
    });
    expect(parseHash(`#template/${TEMPLATE_ID}`)).toEqual({
      tab: "templates", sessionId: null, templateId: TEMPLATE_ID, templateView: "detail",
    });
    expect(parseHash(`#template/${TEMPLATE_ID}/review`)).toEqual({
      tab: "templates", sessionId: null, templateId: TEMPLATE_ID, templateView: "review",
    });
    expect(parseHash(`#template/${TEMPLATE_ID}/run`)).toEqual({
      tab: "templates", sessionId: null, templateId: TEMPLATE_ID, templateView: "run",
    });
  });

  it("serializes application navigation state", () => {
    expect(toHash({ tab: "overview", sessionId: null })).toBe("#overview");
    expect(toHash({ tab: "sessions", sessionId: "s001" })).toBe("#session/s001");
    expect(toHash({ tab: "templates", templateView: "new" })).toBe("#template/new");
  });

  it("round-trips every template route through parse and serialize", () => {
    for (const hash of [
      "#templates",
      "#template/new",
      `#template/${TEMPLATE_ID}`,
      `#template/${TEMPLATE_ID}/review`,
      `#template/${TEMPLATE_ID}/run`,
      "#session/s001",
      "#overview",
      "#devices",
    ]) {
      expect(toHash(parseHash(hash))).toBe(hash);
    }
  });

  it("redirects the legacy blank-session link to template creation", () => {
    // Sessions can no longer be created without a template, so an old #create
    // bookmark must land somewhere that still works.
    expect(parseHash("#create")).toEqual({
      tab: "templates", sessionId: null, templateId: null, templateView: "new",
    });
    expect(toHash(parseHash("#create"))).toBe("#template/new");
  });

  it("falls back to the templates list for an unusable template id", () => {
    for (const hash of [
      "#template/",
      "#template//review",
      "#template/not a valid id",
      "#template/../secrets",
      `#template/${TEMPLATE_ID}/unknown-action`,
      `#template/${TEMPLATE_ID}/run/extra`,
    ]) {
      expect(parseHash(hash)).toEqual({
        tab: "templates", sessionId: null, templateId: null, templateView: null,
      });
    }
  });

  it("serializes a template view with no usable id back to the list", () => {
    expect(toHash({ tab: "templates", templateId: null, templateView: "detail" })).toBe(
      "#templates",
    );
  });

  it("falls back to overview for unknown routes", () => {
    expect(parseHash("#not-a-route")).toEqual({
      tab: "overview", sessionId: null, templateId: null, templateView: null,
    });
  });
});
