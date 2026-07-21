const validTabs = new Set([
  "overview",
  "sessions",
  "experiments",
  "devices",
  "templates",
  "incidents",
  "operations",
  "system-health",
]);

export function parseHash(hash = "") {
  const value = hash.replace(/^#/, "");
  if (value === "create") return { tab: "sessions", sessionId: null, creating: true };
  if (value.startsWith("session/")) {
    return { tab: "sessions", sessionId: value.slice("session/".length) || null, creating: false };
  }
  return {
    tab: validTabs.has(value) ? value : "overview",
    sessionId: null,
    creating: false,
  };
}

export function toHash({ tab, sessionId, creating }) {
  if (creating) return "#create";
  if (sessionId) return `#session/${sessionId}`;
  return `#${validTabs.has(tab) ? tab : "overview"}`;
}
