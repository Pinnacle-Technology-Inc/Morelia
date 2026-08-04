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

// What a template route is asking for. `null` means the plain Templates list.
const templateViews = new Set(["new", "detail", "review", "run"]);

// Routes address templates by their internal, server-minted id — never by
// filename. A file can be renamed on disk without changing the revision it
// holds, so a filename-keyed URL would silently point somewhere else after a
// rename; the id survives it. This pattern only rejects obviously unusable
// values (empty, path fragments, query junk) rather than pinning the id's
// current 32-hex shape, so the router does not have to change if that does.
const idPattern = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;

const emptyRoute = { tab: "overview", sessionId: null, templateId: null, templateView: null };

function isValidId(value) {
  return typeof value === "string" && idPattern.test(value);
}

function templatesList() {
  return { tab: "templates", sessionId: null, templateId: null, templateView: null };
}

function parseTemplateRoute(rest) {
  const [id, action, ...extra] = rest.split("/");

  // "new" occupies the id position because creation has no template yet. Real
  // ids cannot collide with it: they are hex digests, never the literal "new".
  if (id === "new" && !action) {
    return { tab: "templates", sessionId: null, templateId: null, templateView: "new" };
  }
  // Anything unrecognizable falls back to the list rather than rendering a
  // detail page for a template that cannot be fetched.
  if (!isValidId(id) || extra.length) return templatesList();
  if (!action) {
    return { tab: "templates", sessionId: null, templateId: id, templateView: "detail" };
  }
  if (action === "review" || action === "run") {
    return { tab: "templates", sessionId: null, templateId: id, templateView: action };
  }
  return templatesList();
}

export function parseHash(hash = "") {
  const value = hash.replace(/^#/, "");

  // Legacy blank-session creation. Sessions now always originate from a
  // registered template, so an old bookmark lands on template creation instead
  // of a route that can no longer produce anything.
  if (value === "create") {
    return { tab: "templates", sessionId: null, templateId: null, templateView: "new" };
  }
  if (value === "template" || value === "templates") return templatesList();
  if (value.startsWith("template/")) {
    return parseTemplateRoute(value.slice("template/".length));
  }
  if (value.startsWith("session/")) {
    return {
      tab: "sessions",
      sessionId: value.slice("session/".length) || null,
      templateId: null,
      templateView: null,
    };
  }
  return { ...emptyRoute, tab: validTabs.has(value) ? value : "overview" };
}

export function toHash({ tab, sessionId, templateId, templateView } = {}) {
  if (templateView === "new") return "#template/new";
  if (templateView && templateViews.has(templateView)) {
    // A detail/review/run route without a usable id has nothing to show, so it
    // serializes back to the list — the same place parseHash sends it.
    if (!isValidId(templateId)) return "#templates";
    return templateView === "detail"
      ? `#template/${templateId}`
      : `#template/${templateId}/${templateView}`;
  }
  if (sessionId) return `#session/${sessionId}`;
  return `#${validTabs.has(tab) ? tab : "overview"}`;
}
