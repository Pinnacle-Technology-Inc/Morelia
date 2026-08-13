export const MAX_SESSION_EVENTS = 500;
export const MAX_EVENT_RECONNECTS = 5;
export const SESSION_ACTIVITY_EVENT_TYPES = Object.freeze([
  "activity.recorded",
  "gap.recorded",
]);

const SESSION_ACTIVITY_EVENT_TYPE_SET = new Set(SESSION_ACTIVITY_EVENT_TYPES);

export const SessionEventState = Object.freeze({
  IDLE: "idle", CONNECTING: "connecting", LIVE: "live", RECONNECTING: "reconnecting", STALE: "stale", UNAVAILABLE: "unavailable", STOPPED: "stopped",
});

export function isSessionActivityEvent(event) {
  return SESSION_ACTIVITY_EVENT_TYPE_SET.has(event?.type) && Boolean(event?.data?.activity);
}

export function buildSessionEventsUrl({ apiBase = "", sessionId, after = null } = {}) {
  if (sessionId == null) throw new Error("sessionId is required");
  const base = String(apiBase).replace(/\/$/, "");
  const params = new URLSearchParams();
  if (after != null) params.set("after", String(after));
  const query = params.toString();
  return `${base}/api/v1/sessions/${encodeURIComponent(sessionId)}/events${query ? `?${query}` : ""}`;
}

export function createSessionEventStream({ sessionId, apiBase = "", EventSourceImpl = globalThis.EventSource, maxEvents = MAX_SESSION_EVENTS, maxReconnects = MAX_EVENT_RECONNECTS, onChange } = {}) {
  let source = null;
  let closed = false;
  let generation = 0;
  let reconnects = 0;
  let timer = null;
  let activeSessionId = sessionId;
  let lastId = null;
  const seen = new Set();
  const snapshot = { state: SessionEventState.IDLE, sessionId, events: [], lastId: null, error: null };

  function emit() { onChange?.({ ...snapshot, events: snapshot.events.slice() }); }
  function setState(state, error = null) { snapshot.state = state; snapshot.error = error; emit(); }
  function closeSource() { if (source) { source.close(); source = null; } }
  function schedule() {
    if (closed || reconnects >= maxReconnects) { setState(snapshot.events.length ? SessionEventState.STALE : SessionEventState.UNAVAILABLE, snapshot.error ?? "Session activity stream unavailable"); return; }
    setState(SessionEventState.RECONNECTING);
    const delay = Math.min(8000, 500 * 2 ** reconnects++);
    timer = setTimeout(() => { timer = null; connect(); }, delay);
  }
  function handle(event, mine) {
    if (closed || mine !== generation) return;
    const id = event?.lastEventId != null && event.lastEventId !== "" ? String(event.lastEventId) : null;
    if (id && seen.has(id)) return;
    let data;
    try { data = typeof event?.data === "string" ? JSON.parse(event.data) : event?.data; } catch { return; }
    if (data?.session_id != null && String(data.session_id) !== String(activeSessionId)) return;
    if (id) { seen.add(id); lastId = id; snapshot.lastId = id; }
    snapshot.events = [...snapshot.events, { id, type: event?.type ?? "message", data }].slice(-Math.max(1, Math.trunc(maxEvents)));
    reconnects = 0;
    setState(SessionEventState.LIVE);
  }
  function connect() {
    if (closed) return;
    closeSource();
    if (!EventSourceImpl) { setState(SessionEventState.UNAVAILABLE, "EventSource is unavailable in this browser"); return; }
    setState(reconnects ? SessionEventState.RECONNECTING : SessionEventState.CONNECTING);
    const mine = generation;
    try { source = new EventSourceImpl(buildSessionEventsUrl({ apiBase, sessionId: activeSessionId, after: lastId })); }
    catch (error) { setState(SessionEventState.UNAVAILABLE, error?.message ?? "Could not open activity stream"); return; }
    source.onopen = () => { if (mine === generation && !closed) setState(SessionEventState.LIVE); };
    source.onmessage = (event) => handle(event, mine);
    for (const type of [
      "runtime.report",
      "runtime.command_failed",
      ...SESSION_ACTIVITY_EVENT_TYPES,
    ]) {
      source.addEventListener?.(type, (event) => handle(event, mine));
    }
    source.onerror = () => { if (mine !== generation || closed) return; closeSource(); schedule(); };
  }
  function stop() { closed = true; generation += 1; if (timer) clearTimeout(timer); closeSource(); setState(SessionEventState.STOPPED); }
  function retarget(nextSessionId) { generation += 1; closed = false; activeSessionId = nextSessionId; closeSource(); reconnects = 0; lastId = null; seen.clear(); snapshot.sessionId = nextSessionId; snapshot.events = []; snapshot.lastId = null; snapshot.error = null; connect(); }
  return { start: () => { closed = false; connect(); }, stop, disconnect: stop, retarget, getSnapshot: () => ({ ...snapshot, events: snapshot.events.slice() }) };
}
