import { requestJson } from "./api-client";

export async function loadDeviceTemplates() {
  const value = await requestJson("/api/v1/device-templates");
  if (!Array.isArray(value)) throw new TypeError("The device template API returned an unexpected response shape.");
  return value;
}

export async function loadDeviceTemplateCatalog() {
  const value = await requestJson("/api/v1/device-templates/catalog");
  if (!Array.isArray(value)) throw new TypeError("The device template catalog API returned an unexpected response shape.");
  return value;
}

export async function loadDeviceTemplateTypes() {
  const value = await requestJson("/api/v1/device-templates/supported-types");
  if (!Array.isArray(value)) throw new TypeError("The device template type API returned an unexpected response shape.");
  return value;
}

export async function loadDeviceTemplate(name) {
  const value = await requestJson(`/api/v1/device-templates/${encodeURIComponent(name)}`);
  if (!value || typeof value !== "object") throw new TypeError("The device template API returned an unexpected response shape.");
  return value;
}

export async function loadSessionTemplates() {
  const value = await requestJson("/api/v1/session-templates");
  if (!Array.isArray(value)) throw new TypeError("The session template API returned an unexpected response shape.");
  return value.map(normalizeTemplate);
}

// Stored templates plus on-disk drafts, tagged by `source`. The browser cannot
// read the session-template directory, so the backend assembles the same
// combined view the CLI builds locally.
export async function loadSessionTemplateCatalog() {
  const value = await requestJson("/api/v1/session-templates/catalog");
  if (!Array.isArray(value)) throw new TypeError("The session template catalog API returned an unexpected response shape.");
  return value.map(normalizeTemplate);
}

async function send(path, method, body) {
  return requestJson(path, {
    method,
    headers: { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

export const createDeviceTemplate = (payload) => send("/api/v1/device-templates", "POST", payload);
export const matchDeviceTemplate = (payload) => send("/api/v1/device-templates/match", "POST", payload);
export const updateDeviceTemplate = (name, payload) => send(`/api/v1/device-templates/${encodeURIComponent(name)}`, "PUT", payload);
export const renameDeviceTemplate = (name, newName) => send(`/api/v1/device-templates/${encodeURIComponent(name)}/rename`, "POST", { new_name: newName });
export const deleteDeviceTemplate = (name) => send(`/api/v1/device-templates/${encodeURIComponent(name)}`, "DELETE");
export const validateDeviceTemplateToml = (toml) =>
  send("/api/v1/device-templates/validations", "POST", { toml });
export async function loadDeviceTemplateSource(reference) {
  const value = await requestJson(`/api/v1/device-template-sources/${byReference(reference)}`);
  if (!value || typeof value.toml !== "string") {
    throw new TypeError("The device template source API returned an unexpected response shape.");
  }
  return value;
}
export const repairDeviceTemplateSource = (reference, toml) =>
  send(`/api/v1/device-template-sources/${byReference(reference)}`, "PUT", { toml });
export const createSessionTemplate = (payload) => send("/api/v1/session-templates", "POST", payload);
export const validateSessionTemplateToml = (toml) =>
  send("/api/v1/session-templates/validations", "POST", { toml });
export const createSessionTemplateFromToml = ({ name, toml }) =>
  send("/api/v1/session-templates/imports", "POST", { name, toml });
export const updateSessionTemplate = (name, payload) => send(`/api/v1/session-templates/${encodeURIComponent(name)}`, "PUT", payload);
export const deleteSessionTemplate = (name) => send(`/api/v1/session-templates/${encodeURIComponent(name)}`, "DELETE");
export async function loadSessionTemplateSource(reference) {
  const value = await requestJson(`/api/v1/session-template-sources/${byReference(reference)}`);
  if (!value || typeof value.toml !== "string") {
    throw new TypeError("The session template source API returned an unexpected response shape.");
  }
  return value;
}
export async function repairSessionTemplateSource(reference, toml) {
  return normalizeTemplate(
    await send(`/api/v1/session-template-sources/${byReference(reference)}`, "PUT", { toml }),
  );
}

// --- registry resource -----------------------------------------------------

// The states the backend can report. Anything outside this set is a contract
// break, not something to guess a rendering for.
export const TEMPLATE_STATES = Object.freeze([
  "DISCOVERED",
  "PENDING",
  "ACTIVE",
  "DUPLICATE",
  "AMBIGUOUS_RENAME",
  "CHANGED",
  "ARCHIVED",
  "MISSING",
  "INVALID",
]);

// Exactly the action names the backend puts in `allowed_actions`. The portal
// never adds to this vocabulary: an action the server did not offer is an
// action that cannot legally be taken.
const SERVER_ACTIONS = Object.freeze({
  register: {
    id: "register",
    label: "Register",
    title: "Give this file a registry identity. The TOML file is not modified.",
  },
  accept_change: {
    id: "accept_change",
    label: "Accept as new revision",
    title: "Record the edited file as a new active revision. Your TOML file is not rewritten.",
    confirm:
      "Accept this file as a new revision?\n\n" +
      "A new registry entry becomes ACTIVE. Past runs keep their recorded source revision. " +
      "Your TOML file is not modified by this action.",
  },
  refresh_dependency_revision: {
    id: "refresh_dependency_revision",
    label: "Use current device revisions",
    title: "Pin the current linked device-template revisions and accept them as a new session-template revision.",
    confirm:
      "Use the current linked device-template revisions?\n\n" +
      "The hashes shown in the warnings will replace the old pins in this session template. " +
      "This creates a new active session-template revision; past runs keep their recorded revision.",
  },
  archive: {
    id: "archive",
    label: "Archive",
    title: "Retire this revision. The file stays on disk and stays readable.",
    confirm:
      "Archive this template revision?\n\n" +
      "It can no longer start runs. The TOML file stays on disk and existing " +
      "sessions keep their own frozen copy of it.",
  },
  resolve_rename: {
    id: "resolve_rename",
    label: "Select the original",
    title: "Several files share this revision's configuration. Choose which one is the renamed original.",
  },
});

function asList(value) {
  return Array.isArray(value) ? value : [];
}

/** Normalize one registry resource, rejecting shapes the UI cannot render. */
export function normalizeTemplate(raw) {
  if (!raw || typeof raw !== "object") {
    throw new TypeError("The session template API returned an unexpected response shape.");
  }
  if (typeof raw.state !== "string" || !TEMPLATE_STATES.includes(raw.state)) {
    throw new TypeError(`The session template API returned an unknown state: ${String(raw.state)}`);
  }
  return {
    templateId: raw.template_id ?? null,
    name: raw.name ?? "",
    reference: raw.reference ?? "",
    registeredHash: raw.registered_hash ?? null,
    observedHash: raw.observed_hash ?? null,
    state: raw.state,
    lifecycleState: raw.lifecycle_state ?? null,
    integrityState: raw.integrity_state ?? null,
    lineageParentId: raw.lineage_parent_id ?? null,
    duplicateOfTemplateId: raw.duplicate_of_template_id ?? null,
    content: raw.content ?? null,
    warnings: asList(raw.warnings),
    runnable: typeof raw.runnable === "boolean" ? raw.runnable : undefined,
    runBlockers: asList(raw.run_blockers),
    allowedActions: asList(raw.allowed_actions).filter((action) => action in SERVER_ACTIONS),
    // Only the catalog route counts runs. `null` means "not counted here", which
    // the catalog renders as an em dash rather than as a confident zero.
    runCount: typeof raw.run_count === "number" ? raw.run_count : null,
    latestSession: raw.latest_session ?? null,
    createdAt: raw.created_at ?? null,
    updatedAt: raw.updated_at ?? null,
  };
}

/**
 * How much this template configures, as the catalog's `streams / sinks` pair.
 *
 * Read off the template's own content rather than a server-side count: the
 * content is already on the wire, and a template that failed to parse has no
 * flows to count, which is honestly reported as 0 / 0 next to its INVALID state.
 */
export function templateFlowSummary(template) {
  const flows = Array.isArray(template?.content?.device_flows) ? template.content.device_flows : [];
  return {
    streams: flows.length,
    sinks: flows.reduce((total, flow) => total + (Array.isArray(flow?.sinks) ? flow.sinks.length : 0), 0),
  };
}

const DEVICE_TEMPLATE_DRIFT_PATTERN =
  /^flow\s+\d+:\s+device template changed at\s+.+?:\s+expected\s+[a-f0-9]{64},\s+found\s+[a-f0-9]{64}$/i;

/** A pinned device-template revision changed, so this session revision cannot be reproduced. */
export function hasDeviceTemplateDrift(template) {
  return asList(template?.warnings).some((warning) =>
    DEVICE_TEMPLATE_DRIFT_PATTERN.test(String(warning).trim()),
  );
}

/** Return the invalid dependency path the backend says an operator can repair. */
export function deviceTemplateRepairTarget(template) {
  const blocker = asList(template?.runBlockers).find(
    (candidate) => candidate?.recovery_action === "repair_device_template" &&
      typeof candidate?.device_template_path === "string" &&
      candidate.device_template_path.trim(),
  );
  return blocker?.device_template_path.trim() || null;
}

/** Only a reproducible ACTIVE revision can produce a run. */
export function canRunTemplate(template) {
  if (template?.state !== "ACTIVE") return false;
  if (typeof template.runnable === "boolean") return template.runnable;
  // Compatibility for an older backend during a rolling deployment. Once the
  // typed contract is present, it is the only authority for run eligibility.
  return !hasDeviceTemplateDrift(template);
}

/** A template can be opened only once it has a durable identity to open by. */
export function canOpenTemplate(template) {
  return Boolean(template?.templateId);
}

/**
 * The controls to render for one template, in display order.
 *
 * Server-owned actions come strictly from `allowed_actions` — the portal never
 * derives a lifecycle transition itself, so a state the backend considers
 * frozen simply renders no buttons. `open`, `run`, and `open_original` are
 * client-side navigation, not transitions, which is why they are decided here.
 */
export function templateControls(template) {
  const controls = [];
  if (canOpenTemplate(template)) {
    controls.push({ id: "open", label: "Open", kind: "navigate" });
  }
  if (canRunTemplate(template)) {
    controls.push({ id: "run", label: "Start run", kind: "navigate" });
  }
  if (template?.state === "DUPLICATE" && template.duplicateOfTemplateId) {
    controls.push({ id: "open_original", label: "Open original", kind: "navigate" });
  }
  for (const action of template?.allowedActions ?? []) {
    controls.push({ ...SERVER_ACTIONS[action], kind: "action" });
  }
  return controls;
}

/** Operator-facing explanation of why a state cannot run. Never a transition. */
export function templateStateHint(template) {
  const blockerMessage = (template?.state === "ACTIVE" ? asList(template?.runBlockers) : [])
    .map((blocker) => blocker?.message)
    .find((message) => typeof message === "string" && message.trim());
  if (blockerMessage) return blockerMessage;
  if (template?.state === "ACTIVE" && hasDeviceTemplateDrift(template)) {
    return "A linked device template changed after this session template was saved. Refresh the pinned device-template revision before starting a run.";
  }
  return {
    DISCOVERED: "This file has no registry identity yet. Register it to make it runnable.",
    PENDING: "A previous write did not finish. Reconciliation repairs this automatically.",
    ACTIVE: "",
    DUPLICATE: "A copy of a registered template. Only the registered original can run.",
    AMBIGUOUS_RENAME: "Several files match this revision. Select which one is the original.",
    CHANGED: "The file on disk no longer matches the accepted revision. Review the change and accept it as a new revision before running.",
    ARCHIVED: "Archived. Restore it as a new revision if you need to run it again.",
    MISSING: "The registered file cannot be found. Restore it, or resolve a rename.",
    INVALID: "The file cannot be parsed. Repair it on disk.",
  }[template?.state] ?? "";
}

// --- registry actions ------------------------------------------------------
// One function per backend action. Reference-addressed routes take the flat
// filename; identity-addressed routes take the internal id.

const byReference = (reference) => reference.split("/").map(encodeURIComponent).join("/");

export async function loadSessionTemplate(reference) {
  return normalizeTemplate(await requestJson(`/api/v1/session-templates/${byReference(reference)}`));
}

export async function registerDiscoveredTemplate(reference) {
  return normalizeTemplate(
    await send(`/api/v1/session-templates/${byReference(reference)}/actions/register`, "POST"),
  );
}

export async function acceptTemplateChange(templateId) {
  return normalizeTemplate(
    await send(`/api/v1/session-templates/${encodeURIComponent(templateId)}/actions/accept-change`, "POST"),
  );
}

export async function refreshTemplateDependencyRevision(templateId) {
  return normalizeTemplate(
    await send(
      `/api/v1/session-templates/${encodeURIComponent(templateId)}/actions/refresh-dependency-revision`,
      "POST",
    ),
  );
}

export async function archiveTemplate(templateId) {
  return normalizeTemplate(
    await send(`/api/v1/session-templates/${encodeURIComponent(templateId)}/actions/archive`, "POST"),
  );
}

export async function resolveTemplateRename(templateId, selectedRelativePath) {
  return normalizeTemplate(
    await send(
      `/api/v1/session-templates/${encodeURIComponent(templateId)}/actions/resolve-rename`,
      "POST",
      { selected_relative_path: selectedRelativePath },
    ),
  );
}

/**
 * Import user-authored configuration through the same create contract.
 *
 * Returns the registered template. A configuration that already exists comes
 * back as a 409 whose problem body carries `existing_template` — the caller
 * opens that template rather than renaming or retrying, so one configuration
 * never acquires a second identity.
 */
export const importSessionTemplate = (payload) => createSessionTemplate(payload);

/** The existing template a duplicate 409 points at, or null if it was a different conflict. */
export function duplicateTemplateFrom(error) {
  const problem = error?.problem;
  if (problem?.code !== "duplicate_template") return null;
  return problem.existing_template ?? null;
}
