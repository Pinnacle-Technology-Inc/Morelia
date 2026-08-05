// Reconciling a session template with the devices an operator actually picks:
// what settings each device should hold, and what outputs each stream starts
// with. Kept out of the wizard component because these rules are the subtle
// part — they decide how often an operator is interrupted, and they are the
// only thing standing between a template and a silently mismatched run.

/**
 * Normalize a device-template reference to a comparable key.
 *
 * Mirrors the backend's ``device_templates._normalize_reference`` so the three
 * forms that reach the frontend — a stored ``device-templates/pod-high.toml``
 * path, a bare filename, and the CLI's portable ``pod-high`` name — all join.
 */
export function normalizeTemplateRef(value) {
  if (!value) return "";
  return String(value)
    .replace(/\\/g, "/")
    .replace(/^device-templates\//, "")
    .replace(/\.toml$/i, "")
    .toLowerCase();
}

/** The device template a session-template flow points at, or null. */
export function deviceTemplateForFlow(flow, deviceTemplates = []) {
  const reference = flow?.device_template_path || flow?.device_template || "";
  if (!reference) return null;
  const key = normalizeTemplateRef(reference);
  return (
    deviceTemplates.find(
      (template) =>
        normalizeTemplateRef(template.file_path) === key ||
        normalizeTemplateRef(template.name) === key,
    ) ?? null
  );
}

/**
 * Compare a device template's parameters against a device config's.
 *
 * Strict semantics: the template is the complete picture of what the device
 * should hold, so a key present on only one side is a difference rather than an
 * omission to ignore. That means a device carrying extra tuning the template
 * never mentions reads as drifted — deliberately, because adopting the template
 * would drop that tuning and the operator should see it go.
 *
 * Both sides pass through the backend's registry before storage, so values are
 * already canonical (``"10"`` is stored as ``10``) and compare directly. Values
 * are scalars or flat arrays, which is what makes JSON encoding a sound
 * equality test here.
 *
 * Returns one row per key, sorted, each marked `same` or not — callers render
 * the matching rows for context and gate on the rest.
 */
export function compareParameters(templateParameters = {}, deviceParameters = {}) {
  const keys = [...new Set([...Object.keys(templateParameters), ...Object.keys(deviceParameters)])].sort();
  return keys.map((key) => {
    const inTemplate = key in templateParameters;
    const inDevice = key in deviceParameters;
    return {
      key,
      inTemplate,
      inDevice,
      templateValue: templateParameters[key],
      deviceValue: deviceParameters[key],
      same:
        inTemplate &&
        inDevice &&
        JSON.stringify(templateParameters[key]) === JSON.stringify(deviceParameters[key]),
    };
  });
}

/** True when at least one parameter needs an operator decision. */
export function hasDrift(rows) {
  return rows.some((row) => !row.same);
}

/**
 * Which template flow a device answers to.
 *
 * A template can carry several flows of the same device type, and nothing in
 * the plan says which one a hand-picked device stands in for. The rule: take
 * the first flow of a matching type that no other selection has claimed, so
 * two devices of one type map to two distinct flows instead of both to the
 * first. Returns null when no flow matches — the device is an extra stream the
 * template never asked for, and imposes no settings expectation.
 */
export function matchFlowIndex(device, flows = [], deviceTemplates = [], claimedIndexes = []) {
  const taken = new Set(claimedIndexes);
  const index = flows.findIndex(
    (flow, position) =>
      !taken.has(position) && deviceTemplateForFlow(flow, deviceTemplates)?.type === device?.type,
  );
  return index === -1 ? null : index;
}

// --- Sink import and default naming ----------------------------------------
//
// The backend already has a complete answer for "where does this file go" when
// a sink omits ``sink_location`` (manifests._allocate_sink_location): the run's
// hyphenated session name under its dataflow directory. The two paths behave
// differently on collision — an allocated path
// deduplicates (-2, -3, ...), an operator-supplied one raises
// SinkLocationExists on purpose. So the wizard's job is to *show* what the
// backend would pick and otherwise stay out of the way, exactly as the Session
// Name field shows the backend's generated name as a placeholder rather than
// submitting it as a value.

/** Make an identity safe as one path segment — mirrors manifests._path_segment. */
export function pathSegment(value) {
  return String(value ?? "").replace(/[:/\\]/g, "-");
}

/**
 * A sink identifier unique within one stream.
 *
 * ``sink_name`` defaults to the sink type on the backend, but it must also be
 * unique within a source (session_config rejects duplicates), so a second CSV
 * on the same device cannot also be "csv". Sinks the operator left unnamed will
 * themselves fall back to their type, so those count as taken too.
 */
export function uniqueSinkIdentifier(sinkType, existing = []) {
  const taken = new Set();
  for (const sink of existing) {
    const name = (sink?.sink_name ?? "").trim();
    taken.add(name || sink?.sink_type);
  }
  if (!taken.has(sinkType)) return sinkType;
  let suffix = 2;
  while (taken.has(`${sinkType}-${suffix}`)) suffix += 1;
  return `${sinkType}-${suffix}`;
}

/**
 * Legacy device/sink filename fallback for callers without a session name.
 */
export function defaultSinkStem(device, sinkIdentifier) {
  const deviceId = `${device?.type ?? ""}:${device?.hardwareId ?? ""}`;
  return `${pathSegment(deviceId)}-${pathSegment(sinkIdentifier)}`;
}

/** Replace the default `Run` label while retaining the backend's suggested number. */
export function sessionNameFromSuggestion(suggestion, requestedName = "") {
  const label = String(requestedName ?? "").trim();
  if (!label) return String(suggestion ?? "");
  return String(suggestion ?? "").replace(/ • Run (\d+)$/, ` • ${label} $1`);
}

/** Hyphenated template + session label + run number for a default output file. */
function filenameSlug(value) {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, "-")
    .replace(/^-+|-+$/g, "");
}

/** The required `<device-code>-<device-name>` portion of a run filename. */
export function deviceRunFileStem(device) {
  const rawType = String(device?.type ?? "");
  const code = rawType.match(/\d+/)?.[0] || filenameSlug(rawType) || "device";
  const configId = device?.configId ?? (Number.isInteger(device?.id) ? device.id : null);
  const deviceName = filenameSlug(device?.nickname) || `config-${configId ?? "unknown"}`;
  return `${filenameSlug(code)}-${deviceName}`;
}

export function defaultRunFileStem(sessionName, device, duplicateOrdinal = 1) {
  const runStem = `${filenameSlug(sessionName)}-${deviceRunFileStem(device)}`;
  return duplicateOrdinal > 1 ? `${runStem}-${duplicateOrdinal}` : runStem;
}

/**
 * A template flow's sinks, in the wizard's editor shape.
 *
 * Mirrors the backend's ``_resolve_sinks``: the canonical ``sinks[]`` list, or
 * the legacy flattened form (``sink_type`` on the flow itself, optionally with
 * ``sink_location``/``sink_parameters``) which local drafts still use and which
 * reaches the browser unnormalized. Mixing the two is the backend's error to
 * raise, not ours — the list simply wins here.
 *
 * A stored ``sink_location`` is read as a FOLDER, not a file path. A template
 * is a reusable recipe, so its destination means "put this run's output here";
 * taking it as an exact filename would make the second session from that
 * template fail with SinkLocationExists.
 *
 * ``sink_name`` is dropped when it merely equals the sink type, because that is
 * the backend's own default written out (see library-export.toml) rather than a
 * name anybody chose — keeping it would pin a file called "csv.csv".
 */
export function templateSinksForFlow(flow) {
  const raw = Array.isArray(flow?.sinks)
    ? flow.sinks
    : flow?.sink_type
      ? [{ sink_type: flow.sink_type, sink_location: flow.sink_location, sink_parameters: flow.sink_parameters }]
      : [];
  return raw.filter((sink) => sink?.sink_type).map((sink) => {
    const name = (sink.sink_name ?? "").trim();
    const imported = {
      sink_type: sink.sink_type,
      sink_name: name === sink.sink_type ? "" : name,
      sink_folder: (sink.sink_location ?? "").trim(),
    };
    // Carried through opaquely: the wizard has no editor for sink parameters
    // (an Influx token env name, say), and dropping them on import would
    // quietly break every sink that needs one.
    if (sink.sink_parameters && Object.keys(sink.sink_parameters).length > 0) {
      imported.sink_parameters = sink.sink_parameters;
    }
    return imported;
  });
}
