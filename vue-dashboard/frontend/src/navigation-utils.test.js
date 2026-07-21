import { describe, expect, it } from "vitest";
import { parseHash, toHash } from "./navigation-utils";

describe("hash navigation", () => {
  it("parses top-level dashboard tabs", () => {
    expect(parseHash("#sessions")).toEqual({ tab: "sessions", sessionId: null, creating: false });
    expect(parseHash("#devices")).toEqual({ tab: "devices", sessionId: null, creating: false });
    expect(parseHash("#templates")).toEqual({ tab: "templates", sessionId: null, creating: false });
    expect(parseHash("#operations")).toEqual({ tab: "operations", sessionId: null, creating: false });
  });

  it("parses session detail and create-session states", () => {
    expect(parseHash("#session/s002")).toEqual({ tab: "sessions", sessionId: "s002", creating: false });
    expect(parseHash("#create")).toEqual({ tab: "sessions", sessionId: null, creating: true });
  });

  it("serializes application navigation state", () => {
    expect(toHash({ tab: "overview", sessionId: null, creating: false })).toBe("#overview");
    expect(toHash({ tab: "sessions", sessionId: "s001", creating: false })).toBe("#session/s001");
  });

  it("falls back to overview for unknown routes", () => {
    expect(parseHash("#not-a-route")).toEqual({ tab: "overview", sessionId: null, creating: false });
  });
});
