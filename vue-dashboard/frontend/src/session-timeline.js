import { formatCentralTimestamp, timestampMs } from "./datetime";

export const TimelineCategory = Object.freeze({
  DATAFLOW: "dataflow",
  RECOVERY: "recovery",
  SUPERVISION: "supervision",
  OPERATIONS: "operations",
});

const ACTIVITY_CATEGORY = Object.freeze({
  dataflow: TimelineCategory.DATAFLOW,
  gaps: TimelineCategory.DATAFLOW,
  recovery: TimelineCategory.RECOVERY,
  issues: TimelineCategory.SUPERVISION,
  supervision: TimelineCategory.SUPERVISION,
  session: TimelineCategory.OPERATIONS,
});

const ACTIVITY_TONE = Object.freeze({
  success: "good",
  warning: "warn",
  error: "bad",
  info: "neutral",
});

const HEALTHY = "healthy";

export function buildActivityTimeline(activity = []) {
  return asArray(activity).map((entry, index) => ({
    key: `activity:${entry?.activity_id ?? index}`,
    at: entry?.occurred_at ?? entry?.created_at ?? null,
    category: ACTIVITY_CATEGORY[normalize(entry?.category)] ?? TimelineCategory.OPERATIONS,
    tone: ACTIVITY_TONE[normalize(entry?.severity)] ?? "neutral",
    title: entry?.title || "Activity recorded",
    summary: entry?.summary || "A session event was recorded.",
    details: entry?.details ?? entry,
  }));
}

export function formatGapWindow(gap = {}) {
  const start = boundaryTimestamp(gap.gap_start);
  const end = boundaryTimestamp(gap.gap_end);
  if (start == null && end == null) return "Boundaries not reported";
  const window = `${formatBoundary(start)} → ${formatBoundary(end)}`;
  if (start == null || end == null || end < start) return window;
  return `${window} (${formatDuration(end - start)})`;
}

export function buildSessionTimeline({ events = [], incidents = [], gaps = [], operations = [] } = {}) {
  const entries = [];
  let order = 0;
  const add = (entry) => entries.push({ ...entry, _order: order++ });
  const operationIds = new Set(asArray(operations).map((item) => item?.operation_id).filter(Boolean));

  addRuntimeEntries(asArray(events), operationIds, add);
  asArray(incidents).forEach((incident) => addIncidentEntries(incident, add));
  asArray(gaps).forEach((gap) => addGapEntry(gap, add));
  asArray(operations).forEach((operation) => addOperationEntry(operation, add));

  return entries
    .sort((left, right) => timestamp(right.at) - timestamp(left.at) || right._order - left._order)
    .map(({ _order, ...entry }) => entry);
}

export function recentTimelineEntries(entries = [], limit = 3) {
  const count = Math.max(0, Math.trunc(Number(limit) || 0));
  return asArray(entries).slice(0, count);
}

function addRuntimeEntries(events, operationIds, add) {
  const deviceStates = new Map();
  const sinkStates = new Map();
  const recoveryIds = new Set();
  const chronological = events
    .map((event, index) => ({ event, index }))
    .sort((left, right) => eventTimestamp(left.event) - eventTimestamp(right.event) || left.index - right.index);

  for (const { event } of chronological) {
    const data = object(event?.data);
    const at = eventAt(event);

    if (event?.type === "runtime.command_failed") {
      if (data.operation_id && operationIds.has(data.operation_id)) continue;
      add({
        key: `event:${event?.id ?? data.report_id ?? data.sequence ?? orderKey(data)}`,
        at,
        category: TimelineCategory.OPERATIONS,
        tone: "bad",
        title: `${label(data.command || "Command")} failed`,
        summary: data.error_message || data.message || "The runtime command did not complete.",
        details: eventDetails(event),
      });
      continue;
    }

    if (event?.type !== "runtime.report") continue;

    const streamActions = new Map();
    for (const stream of asArray(object(data.diagnostics).streams)) {
      const deviceId = stream?.device_id;
      const action = normalize(stream?.action);
      if (!deviceId || !["unplug_detected", "connection_restored"].includes(action)) continue;
      streamActions.set(deviceId, action);
      const restored = action === "connection_restored";
      const disconnect = object(stream?.disconnect);
      add({
        key: `event:${event?.id ?? data.sequence ?? orderKey(data)}:port:${deviceId}:${action}`,
        at,
        category: TimelineCategory.DATAFLOW,
        tone: restored ? "good" : "warn",
        title: restored ? "Connection restored" : "Unplug detected",
        summary: restored
          ? `${deviceId} resumed recording real samples.`
          : `${deviceId} is recording missing values during the grace period.`,
        details: eventDetails(event, {
          device_id: deviceId,
          action,
          disconnect,
        }),
      });
    }

    if (data.recovery_id && !recoveryIds.has(data.recovery_id)) {
      recoveryIds.add(data.recovery_id);
      add({
        key: `recovery:${data.recovery_id}`,
        at,
        category: TimelineCategory.RECOVERY,
        tone: "warn",
        title: "Recovery started",
        summary: "The runtime reported recovery activity for this dataflow.",
        details: eventDetails(event),
      });
    }

    for (const device of asArray(data.devices)) {
      const deviceId = device?.device_id || "Unknown device";
      const current = normalize(device?.stream_status);
      if (!current) continue;
      const previous = deviceStates.get(deviceId);
      deviceStates.set(deviceId, current);
      if (streamActions.has(deviceId)) continue;
      addHealthTransition({
        add,
        key: `event:${event?.id ?? data.sequence ?? orderKey(data)}:device:${deviceId}`,
        at,
        current,
        previous,
        subject: deviceId,
        disruptedTitle: "Data disrupted",
        resumedTitle: "Data resumed",
        details: eventDetails(event, { device_id: deviceId, previous_status: previous, current_status: current }),
      });
    }

    for (const sink of asArray(data.sinks)) {
      const sinkId = sink?.sink_id || "Unknown output";
      const sinkKey = `${sink?.source_id || "source"}:${sinkId}`;
      const current = normalize(sink?.health);
      if (!current) continue;
      const previous = sinkStates.get(sinkKey);
      sinkStates.set(sinkKey, current);
      addHealthTransition({
        add,
        key: `event:${event?.id ?? data.sequence ?? orderKey(data)}:sink:${sinkKey}`,
        at,
        current,
        previous,
        subject: sinkId,
        message: sink?.message,
        disruptedTitle: "Output disrupted",
        resumedTitle: "Output resumed",
        details: eventDetails(event, { sink_id: sinkId, previous_status: previous, current_status: current }),
      });
    }
  }
}

function addHealthTransition({ add, key, at, current, previous, subject, message, disruptedTitle, resumedTitle, details }) {
  if (current === previous || (previous == null && current === HEALTHY)) return;
  const resumed = current === HEALTHY;
  add({
    key,
    at,
    category: TimelineCategory.DATAFLOW,
    tone: resumed ? "good" : current === "suspect" ? "warn" : "bad",
    title: resumed ? resumedTitle : disruptedTitle,
    summary: resumed
      ? `${subject} returned to healthy operation.`
      : message || `${subject} changed from ${previous || "unreported"} to ${current}.`,
    details,
  });
}

function addIncidentEntries(incident, add) {
  if (!incident || typeof incident !== "object") return;
  const supervision = incident.axis === "control_plane";
  const category = supervision ? TimelineCategory.SUPERVISION : TimelineCategory.DATAFLOW;
  const prefix = supervision ? "Supervision" : "Dataflow";
  const id = incident.incident_id ?? orderKey(incident);
  if (incident.opened_at) {
    add({
      key: `incident:${id}:opened`,
      at: incident.opened_at,
      category,
      tone: "bad",
      title: `${prefix} incident opened`,
      summary: recordSummary(incident, "An incident requires attention."),
      details: incident,
    });
  }
  if (incident.resolved_at) {
    add({
      key: `incident:${id}:resolved`,
      at: incident.resolved_at,
      category,
      tone: "good",
      title: `${prefix} incident resolved`,
      summary: incident.resolution || recordSummary(incident, "The incident was resolved."),
      details: incident,
    });
  }
}

function addGapEntry(gap, add) {
  if (!gap || typeof gap !== "object") return;
  add({
    key: `gap:${gap.gap_id ?? orderKey(gap)}`,
    at: gap.created_at,
    category: TimelineCategory.DATAFLOW,
    tone: "warn",
    title: "Data gap recorded",
    summary: recordSummary(gap, "A discontinuity was recorded in experiment output."),
    details: gap,
  });
}

function addOperationEntry(operation, add) {
  if (!operation || typeof operation !== "object") return;
  const state = normalize(operation.state) || "recorded";
  const command = label(operation.command || "Operation");
  const recovery = Boolean(operation.recovery_id) || normalize(operation.command).includes("recover");
  add({
    key: `operation:${operation.operation_id ?? orderKey(operation)}`,
    at: operation.resolved_at || operation.finished_at || operation.updated_at || operation.created_at,
    category: recovery ? TimelineCategory.RECOVERY : TimelineCategory.OPERATIONS,
    tone: operationTone(state),
    title: `${command} ${label(state).toLowerCase()}`,
    summary: operation.error_message || operation.resolution_note || operationSummary(operation, state),
    details: operation,
  });
}

function operationSummary(operation, state) {
  const target = operation.target_device_id || operation.scope;
  return target ? `${label(state)} for ${target}.` : `${label(state)}.`;
}

function operationTone(state) {
  if (state === "succeeded") return "good";
  if (state === "failed" || state === "uncertain") return "bad";
  return "neutral";
}

function recordSummary(record, fallback) {
  const subject = record.device_id || record.sink_id;
  const reason = record.reason || fallback;
  const confidence = record.confidence ? ` (${label(record.confidence).toLowerCase()} confidence)` : "";
  return `${subject ? `${subject}: ` : ""}${reason}${confidence}`;
}

function eventDetails(event, extra = {}) {
  const data = object(event?.data);
  return {
    event_id: event?.id ?? null,
    event_type: event?.type ?? "message",
    sequence: data.sequence ?? null,
    dataflow_id: data.dataflow_id ?? null,
    runtime_id: data.runtime_id ?? null,
    watchdog_id: data.watchdog_id ?? null,
    report_id: data.report_id ?? null,
    recovery_id: data.recovery_id ?? null,
    ...extra,
  };
}

function eventAt(event) {
  const data = object(event?.data);
  return data.received_at || data.timestamp || event?.received_at || null;
}

function eventTimestamp(event) {
  return timestamp(eventAt(event));
}

function timestamp(value) {
  return timestampMs(value) ?? Number.NEGATIVE_INFINITY;
}

function boundaryTimestamp(boundary) {
  if (typeof boundary === "number" && Number.isFinite(boundary)) return boundary;
  if (!boundary || typeof boundary !== "object") return null;
  const value = Number(boundary.timestamp);
  return Number.isFinite(value) ? value : null;
}

function formatBoundary(seconds) {
  if (seconds == null) return "?";
  return formatCentralTimestamp(seconds * 1000, { fallback: String(seconds) });
}

function formatDuration(seconds) {
  const rounded = Math.round(seconds * 10) / 10;
  return `${rounded.toLocaleString()} second${rounded === 1 ? "" : "s"}`;
}

function label(value) {
  const text = String(value ?? "").replace(/[_-]+/g, " ").trim();
  return text ? `${text.charAt(0).toUpperCase()}${text.slice(1)}` : "";
}

function normalize(value) {
  return String(value ?? "").trim().toLowerCase();
}

function object(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function orderKey(value) {
  return JSON.stringify(value ?? {}).slice(0, 80);
}
