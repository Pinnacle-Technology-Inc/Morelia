import { afterEach, describe, expect, it, vi } from "vitest";
import {
  MAX_RENDERED_POINTS,
  MAX_RECONNECT_ATTEMPTS,
  PLOT_SCHEMA_VERSION,
  PlotConnectionState,
  appendBoundedSamples,
  buildPlotStreamUrl,
  createPlotSubscription,
  parseSseFrame,
} from "./plot-stream";

class FakeEventSource {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.onopen = null;
    this.onerror = null;
    this.onmessage = null;
    this._listeners = new Map();
    FakeEventSource.instances.push(this);
  }

  addEventListener(type, fn) {
    const list = this._listeners.get(type) ?? [];
    list.push(fn);
    this._listeners.set(type, list);
  }

  removeEventListener(type, fn) {
    const list = this._listeners.get(type) ?? [];
    this._listeners.set(
      type,
      list.filter((item) => item !== fn),
    );
  }

  close() {
    this.readyState = 2;
  }

  open() {
    this.readyState = 1;
    this.onopen?.();
  }

  emitPlot(data, lastEventId = String(data.seq ?? "")) {
    const event = { data: JSON.stringify(data), lastEventId };
    for (const fn of this._listeners.get("plot") ?? []) fn(event);
  }

  failClosed() {
    this.readyState = 2;
    this.onerror?.();
  }
}

afterEach(() => {
  FakeEventSource.instances = [];
  vi.useRealTimers();
});

describe("buildPlotStreamUrl", () => {
  it("builds the frozen packet-27 URL with token and optional cursor", () => {
    expect(
      buildPlotStreamUrl({
        apiBase: "http://localhost:5000",
        sessionId: 7,
        sinkId: "browser-plot",
        token: "tok",
        after: 3,
      }),
    ).toBe(
      "http://localhost:5000/api/v1/sessions/7/plot/browser-plot/stream?token=tok&after=3",
    );
  });

  it("rejects missing auth material", () => {
    expect(() =>
      buildPlotStreamUrl({ sessionId: 1, sinkId: "p", token: "" }),
    ).toThrow(/token/i);
  });
});

describe("appendBoundedSamples", () => {
  it("keeps a rolling window and reports evictions", () => {
    const first = appendBoundedSamples([], {
      samples: [[1], [2], [3]],
      channels: ["ch0"],
    }, 4);
    expect(first.samples).toEqual([[1], [2], [3]]);
    expect(first.evicted).toBe(0);

    const next = appendBoundedSamples(first.samples, { samples: [[4], [5]] }, 4);
    expect(next.samples).toEqual([[2], [3], [4], [5]]);
    expect(next.evicted).toBe(1);
  });

  it("never exceeds MAX_RENDERED_POINTS", () => {
    const flood = Array.from({ length: MAX_RENDERED_POINTS + 50 }, (_, i) => [i]);
    const { samples, evicted } = appendBoundedSamples([], { samples: flood });
    expect(samples).toHaveLength(MAX_RENDERED_POINTS);
    expect(evicted).toBe(50);
  });
});

describe("parseSseFrame", () => {
  it("parses plot frames and ignores heartbeats", () => {
    expect(parseSseFrame(": heartbeat\n\n")).toBeNull();
    const frame = parseSseFrame(
      `id: 2\nevent: plot\ndata: ${JSON.stringify({ schema: PLOT_SCHEMA_VERSION, seq: 2 })}\n\n`,
    );
    expect(frame).toEqual({
      id: "2",
      event: "plot",
      data: { schema: PLOT_SCHEMA_VERSION, seq: 2 },
    });
  });
});

describe("createPlotSubscription", () => {
  async function flush() {
    await Promise.resolve();
    await Promise.resolve();
  }

  it("receives ordered batches, tracks drops, and bounds memory", async () => {
    const changes = [];
    const sub = createPlotSubscription({
      sessionId: 1,
      sinkId: "browser-plot",
      token: "tok",
      maxPoints: 3,
      EventSourceImpl: FakeEventSource,
      onChange: (snap) => changes.push(snap),
    });
    sub.start();
    await flush();

    const es = FakeEventSource.instances.at(-1);
    expect(es).toBeTruthy();
    es.open();
    es.emitPlot({
      schema: PLOT_SCHEMA_VERSION,
      session_id: 1,
      sink_id: "browser-plot",
      seq: 0,
      channels: ["ch0"],
      samples: [[1], [2]],
      dropped: 0,
    });
    es.emitPlot({
      schema: PLOT_SCHEMA_VERSION,
      session_id: 1,
      sink_id: "browser-plot",
      seq: 1,
      channels: ["ch0"],
      samples: [[3], [4]],
      dropped: 2,
    });

    const snap = sub.getSnapshot();
    expect(snap.state).toBe(PlotConnectionState.DROPPED);
    expect(snap.dropped).toBe(2);
    expect(snap.samples).toEqual([[2], [3], [4]]);
    expect(snap.channels).toEqual(["ch0"]);
    expect(snap.lastSeq).toBe(1);
    expect(changes.some((c) => c.state === PlotConnectionState.LIVE)).toBe(true);

    sub.disconnect();
    expect(sub.getSnapshot().state).toBe(PlotConnectionState.STOPPED);
  });

  it("reconnects with after= cursor and stops at the retry bound", async () => {
    vi.useFakeTimers();
    const sub = createPlotSubscription({
      sessionId: 3,
      sinkId: "p",
      token: "tok",
      maxReconnectAttempts: 2,
      EventSourceImpl: FakeEventSource,
    });
    sub.start();
    await flush();

    let es = FakeEventSource.instances.at(-1);
    expect(es).toBeTruthy();
    es.open();
    es.emitPlot({
      schema: PLOT_SCHEMA_VERSION,
      session_id: 3,
      sink_id: "p",
      seq: 4,
      samples: [[1]],
      dropped: 0,
    });
    es.failClosed();

    await vi.advanceTimersByTimeAsync(500);
    await flush();
    es = FakeEventSource.instances.at(-1);
    expect(es.url).toContain("after=4");
    es.failClosed();

    await vi.advanceTimersByTimeAsync(1000);
    await flush();
    es = FakeEventSource.instances.at(-1);
    es.failClosed();

    await vi.advanceTimersByTimeAsync(2000);
    await flush();
    expect(sub.getSnapshot().state).toBe(PlotConnectionState.STALE);
    expect(sub.getSnapshot().samples).toEqual([[1]]);
    expect(FakeEventSource.instances.length).toBeLessThanOrEqual(
      1 + MAX_RECONNECT_ATTEMPTS,
    );
    sub.disconnect();
  });

  it("surfaces unauthorized when token resolution fails", async () => {
    const sub = createPlotSubscription({
      sessionId: 1,
      sinkId: "p",
      token: async () => {
        throw new Error("nope");
      },
      EventSourceImpl: FakeEventSource,
    });
    sub.start();
    await flush();
    expect(sub.getSnapshot().state).toBe(PlotConnectionState.UNAUTHORIZED);
    sub.disconnect();
  });

  it("discards prior samples on retarget so stale session data cannot append", async () => {
    const sub = createPlotSubscription({
      sessionId: 1,
      sinkId: "a",
      token: "tok",
      EventSourceImpl: FakeEventSource,
    });
    sub.start();
    await flush();
    FakeEventSource.instances.at(-1).open();
    FakeEventSource.instances.at(-1).emitPlot({
      schema: PLOT_SCHEMA_VERSION,
      session_id: 1,
      sink_id: "a",
      seq: 0,
      samples: [[9]],
      dropped: 0,
    });
    expect(sub.getSnapshot().samples).toEqual([[9]]);

    sub.retarget({ sessionId: 2, sinkId: "b", token: "tok-2" });
    await flush();
    expect(sub.getSnapshot().samples).toEqual([]);
    expect(sub.getSnapshot().sessionId).toBe(2);
    expect(sub.getSnapshot().sinkId).toBe("b");

    // Old identity must not land in the new window.
    sub.pushBatch({
      schema: PLOT_SCHEMA_VERSION,
      session_id: 1,
      sink_id: "a",
      seq: 1,
      samples: [[1]],
      dropped: 0,
    });
    expect(sub.getSnapshot().samples).toEqual([]);

    sub.pushBatch({
      schema: PLOT_SCHEMA_VERSION,
      session_id: 2,
      sink_id: "b",
      seq: 0,
      samples: [[5]],
      dropped: 0,
    });
    expect(sub.getSnapshot().samples).toEqual([[5]]);
    sub.disconnect();
  });
});
