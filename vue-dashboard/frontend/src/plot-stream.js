/**
 * Browser Plot stream client (packet 28).
 *
 * Consumes the packet-27 SSE contract:
 *   GET /api/v1/sessions/<session_id>/plot/<sink_id>/stream
 *   Auth: ?token= or Authorization Bearer (EventSource can only use query token)
 *   Cursor: ?after=<seq> / Last-Event-ID
 *   Schema: plot.samples.v1
 *
 * Holds a bounded rolling sample window, reconnects with the server cursor,
 * and never grows without bound. Connection state is explicit so the UI can
 * show connecting / live / reconnecting / stale / degraded / dropped /
 * unauthorized / stopped separately from source health.
 */

export const PLOT_SCHEMA_VERSION = "plot.samples.v1";

/** Maximum sample rows retained for rendering (rolling window). */
export const MAX_RENDERED_POINTS = 2_000;

/** Automatic reconnect attempts before stopping and requiring manual retry. */
export const MAX_RECONNECT_ATTEMPTS = 5;

/** Base delay (ms) for reconnect backoff; doubles each attempt, capped. */
export const RECONNECT_BASE_DELAY_MS = 500;

export const PlotConnectionState = Object.freeze({
  IDLE: "idle",
  CONNECTING: "connecting",
  LIVE: "live",
  RECONNECTING: "reconnecting",
  STALE: "stale",
  DEGRADED: "degraded",
  DROPPED: "dropped",
  UNAUTHORIZED: "unauthorized",
  STOPPED: "stopped",
  ERROR: "error",
});

/**
 * Build the authenticated plot SSE URL (query-token form; EventSource cannot set headers).
 */
export function buildPlotStreamUrl({
  apiBase = "",
  sessionId,
  sinkId,
  token,
  after = null,
} = {}) {
  if (sessionId == null || sinkId == null || !token) {
    throw new Error("sessionId, sinkId, and token are required to build a plot stream URL");
  }
  const base = String(apiBase ?? "").replace(/\/$/, "");
  const path = `/api/v1/sessions/${encodeURIComponent(sessionId)}/plot/${encodeURIComponent(sinkId)}/stream`;
  const params = new URLSearchParams({ token: String(token) });
  if (after != null && Number(after) >= 0) {
    params.set("after", String(Math.trunc(Number(after))));
  }
  return `${base}${path}?${params}`;
}

/**
 * Append a batch's samples into a rolling window, dropping the oldest rows.
 * Returns a new array (immutable) and the number of rows evicted.
 */
export function appendBoundedSamples(existing, batch, maxPoints = MAX_RENDERED_POINTS) {
  const incoming = Array.isArray(batch?.samples) ? batch.samples : [];
  if (!incoming.length) {
    return { samples: existing ?? [], evicted: 0, channels: batch?.channels ?? null };
  }
  const prior = Array.isArray(existing) ? existing : [];
  const merged = prior.concat(incoming);
  const limit = Math.max(1, Math.trunc(maxPoints));
  if (merged.length <= limit) {
    return {
      samples: merged,
      evicted: 0,
      channels: batch?.channels ?? null,
    };
  }
  const evicted = merged.length - limit;
  return {
    samples: merged.slice(evicted),
    evicted,
    channels: batch?.channels ?? null,
  };
}

/**
 * Parse one SSE frame block into { id, event, data }.
 * Heartbeat comment frames (lines starting with `:`) return null.
 */
export function parseSseFrame(raw) {
  if (!raw || raw.trimStart().startsWith(":")) return null;
  let id = null;
  let event = "message";
  const dataLines = [];
  for (const line of String(raw).split("\n")) {
    if (line.startsWith("id:")) id = line.slice(3).trim();
    else if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (!dataLines.length) return null;
  let data;
  try {
    data = JSON.parse(dataLines.join("\n"));
  } catch {
    return null;
  }
  return { id, event, data };
}

function classifyBatchHealth(batch, connectionState) {
  if (connectionState === PlotConnectionState.UNAUTHORIZED) {
    return PlotConnectionState.UNAUTHORIZED;
  }
  const dropped = Number(batch?.dropped ?? 0);
  if (dropped > 0) return PlotConnectionState.DROPPED;
  if (batch?.connected === false) return PlotConnectionState.DEGRADED;
  return PlotConnectionState.LIVE;
}

/**
 * Create a plot subscription controller.
 *
 * @param {object} options
 * @param {string|number} options.sessionId
 * @param {string} options.sinkId
 * @param {string|(() => string|Promise<string>)} options.token
 * @param {string} [options.apiBase]
 * @param {number} [options.maxPoints]
 * @param {number} [options.maxReconnectAttempts]
 * @param {typeof EventSource} [options.EventSourceImpl] — injectable for tests
 * @param {(snapshot) => void} [options.onChange]
 */
export function createPlotSubscription(options) {
  const {
    sessionId,
    sinkId,
    apiBase = "",
    maxPoints = MAX_RENDERED_POINTS,
    maxReconnectAttempts = MAX_RECONNECT_ATTEMPTS,
    EventSourceImpl = globalThis.EventSource,
    onChange,
  } = options;

  let tokenOption = options.token;
  let closed = false;
  let source = null;
  let reconnectTimer = null;
  let reconnectAttempt = 0;
  let lastSeq = -1;
  let generation = 0;
  let generationSessionId = sessionId;
  let generationSinkId = sinkId;
  let activeSessionId = sessionId;
  let activeSinkId = sinkId;

  const snapshot = {
    state: PlotConnectionState.IDLE,
    samples: [],
    channels: [],
    lastBatch: null,
    lastSeq: -1,
    dropped: 0,
    windowEvicted: 0,
    error: null,
    sessionId,
    sinkId,
  };

  function emit() {
    onChange?.({ ...snapshot, samples: snapshot.samples.slice() });
  }

  function setState(state, error = null) {
    snapshot.state = state;
    snapshot.error = error;
    emit();
  }

  async function resolveToken() {
    if (typeof tokenOption === "function") {
      return await tokenOption();
    }
    return tokenOption;
  }

  function clearReconnect() {
    if (reconnectTimer != null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  }

  function tearDownSource() {
    if (source) {
      source.onopen = null;
      source.onerror = null;
      source.onmessage = null;
      if (typeof source.removeEventListener === "function" && source._plotListener) {
        source.removeEventListener("plot", source._plotListener);
      }
      source.close();
      source = null;
    }
  }

  function scheduleReconnect() {
    if (closed) return;
    if (reconnectAttempt >= maxReconnectAttempts) {
      // Preserve last frame as stale; require manual reconnect.
      setState(
        snapshot.samples.length ? PlotConnectionState.STALE : PlotConnectionState.ERROR,
        snapshot.error ?? "Reconnect limit reached",
      );
      return;
    }
    const attempt = reconnectAttempt;
    reconnectAttempt += 1;
    setState(PlotConnectionState.RECONNECTING);
    const delay = Math.min(8_000, RECONNECT_BASE_DELAY_MS * 2 ** attempt);
    clearReconnect();
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      void connect();
    }, delay);
  }

  function handlePlotData(data, eventId) {
    if (closed) return;
    // Stale-generation guard: ignore frames from a prior session/sink subscription.
    if (
      activeSessionId !== generationSessionId ||
      activeSinkId !== generationSinkId
    ) {
      return;
    }
    if (data?.schema && data.schema !== PLOT_SCHEMA_VERSION) {
      setState(PlotConnectionState.ERROR, `Unsupported plot schema: ${data.schema}`);
      return;
    }
    if (data?.session_id != null && String(data.session_id) !== String(activeSessionId)) {
      return;
    }
    if (data?.sink_id != null && String(data.sink_id) !== String(activeSinkId)) {
      return;
    }

    const seq = data?.seq != null ? Number(data.seq) : Number(eventId);
    if (Number.isFinite(seq) && seq <= lastSeq) {
      return;
    }
    if (Number.isFinite(seq)) lastSeq = seq;

    const { samples, evicted, channels } = appendBoundedSamples(
      snapshot.samples,
      data,
      maxPoints,
    );
    snapshot.samples = samples;
    snapshot.windowEvicted += evicted;
    if (channels?.length) snapshot.channels = [...channels];
    snapshot.lastBatch = data;
    snapshot.lastSeq = lastSeq;
    snapshot.dropped = Number(data?.dropped ?? snapshot.dropped);
    reconnectAttempt = 0;

    const next = classifyBatchHealth(data, snapshot.state);
    setState(next);
  }

  async function connect() {
    if (closed) return;
    clearReconnect();
    tearDownSource();

    if (!EventSourceImpl) {
      setState(PlotConnectionState.ERROR, "EventSource is not available in this browser");
      return;
    }

    setState(
      reconnectAttempt > 0 ? PlotConnectionState.RECONNECTING : PlotConnectionState.CONNECTING,
    );

    let token;
    try {
      token = await resolveToken();
    } catch (err) {
      setState(PlotConnectionState.UNAUTHORIZED, err?.message ?? "Failed to resolve plot token");
      return;
    }
    if (!token) {
      setState(PlotConnectionState.UNAUTHORIZED, "A plot subscription token is required");
      return;
    }

    let url;
    try {
      url = buildPlotStreamUrl({
        apiBase,
        sessionId: activeSessionId,
        sinkId: activeSinkId,
        token,
        after: lastSeq >= 0 ? lastSeq : null,
      });
    } catch (err) {
      setState(PlotConnectionState.ERROR, err.message);
      return;
    }

    const myGeneration = generation;
    try {
      source = new EventSourceImpl(url);
    } catch (err) {
      setState(PlotConnectionState.ERROR, err?.message ?? "Failed to open plot stream");
      scheduleReconnect();
      return;
    }

    source.onopen = () => {
      if (closed || myGeneration !== generation) return;
      setState(PlotConnectionState.LIVE);
    };

    const onPlot = (event) => {
      if (closed || myGeneration !== generation) return;
      let data;
      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }
      handlePlotData(data, event.lastEventId);
    };
    source._plotListener = onPlot;
    source.addEventListener?.("plot", onPlot);

    // Some EventSource polyfills only fire onmessage.
    source.onmessage = onPlot;

    source.onerror = () => {
      if (closed || myGeneration !== generation) return;
      const status = source?.readyState;
      tearDownSource();
      // readyState 2 === CLOSED; browsers surface 401/403 as a hard close.
      if (status === 2 && snapshot.state === PlotConnectionState.CONNECTING && lastSeq < 0) {
        setState(PlotConnectionState.UNAUTHORIZED, "Plot subscription was rejected");
        return;
      }
      scheduleReconnect();
    };
  }

  function stop({ reason = PlotConnectionState.STOPPED } = {}) {
    closed = true;
    clearReconnect();
    tearDownSource();
    setState(reason);
  }

  function disconnect() {
    stop({ reason: PlotConnectionState.STOPPED });
  }

  function reconnect() {
    closed = false;
    reconnectAttempt = 0;
    void connect();
  }

  /**
   * Retarget to a new session/sink. Discards prior samples so reconnect cannot
   * append data from a previous subscription (AC3).
   */
  function retarget({ sessionId: nextSessionId, sinkId: nextSinkId, token: nextToken } = {}) {
    generation += 1;
    clearReconnect();
    tearDownSource();
    closed = false;
    reconnectAttempt = 0;
    lastSeq = -1;
    if (nextSessionId != null) {
      generationSessionId = nextSessionId;
      activeSessionId = nextSessionId;
      snapshot.sessionId = nextSessionId;
    }
    if (nextSinkId != null) {
      generationSinkId = nextSinkId;
      activeSinkId = nextSinkId;
      snapshot.sinkId = nextSinkId;
    }
    if (nextToken !== undefined) {
      tokenOption = nextToken;
    }
    snapshot.samples = [];
    snapshot.channels = [];
    snapshot.lastBatch = null;
    snapshot.lastSeq = -1;
    snapshot.dropped = 0;
    snapshot.windowEvicted = 0;
    snapshot.error = null;
    void connect();
  }

  /** Test/helper: inject a parsed batch without a live EventSource. */
  function pushBatch(batch) {
    handlePlotData(batch, batch?.seq);
  }

  return {
    start: () => {
      closed = false;
      void connect();
    },
    stop: disconnect,
    disconnect,
    reconnect,
    retarget,
    pushBatch,
    getSnapshot: () => ({ ...snapshot, samples: snapshot.samples.slice() }),
  };
}
