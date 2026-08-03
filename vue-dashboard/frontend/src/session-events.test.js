import { afterEach, expect, it, vi } from "vitest";
import { buildSessionEventsUrl, createSessionEventStream } from "./session-events";

afterEach(() => vi.useRealTimers());

class FakeEventSource {
  static instances = [];
  constructor(url) { this.url = url; this.listeners = {}; FakeEventSource.instances.push(this); }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  emit(type, data, id) { (this.listeners[type] ?? this.onmessage)?.({ type, data: JSON.stringify(data), lastEventId: String(id) }); }
  close() { this.closed = true; }
}

it("builds a cursor-resumable session event URL", () => {
  expect(buildSessionEventsUrl({ sessionId: 7, after: 12 })).toBe("/api/v1/sessions/7/events?after=12");
});

it("deduplicates replayed ids, bounds events, and closes on stop/retarget", () => {
  const changes = [];
  const stream = createSessionEventStream({ sessionId: 7, EventSourceImpl: FakeEventSource, maxEvents: 2, onChange: (value) => changes.push(value) });
  stream.start();
  const source = FakeEventSource.instances[0];
  source.emit("runtime.report", { sequence: 1 }, 1);
  source.emit("runtime.report", { sequence: 1 }, 1);
  source.emit("runtime.report", { sequence: 2 }, 2);
  source.emit("runtime.report", { sequence: 3 }, 3);
  expect(stream.getSnapshot().events.map((event) => event.id)).toEqual(["2", "3"]);
  stream.retarget(8);
  expect(source.closed).toBe(true);
  expect(FakeEventSource.instances[1].url).toBe("/api/v1/sessions/8/events");
  stream.stop();
  expect(FakeEventSource.instances[1].closed).toBe(true);
  expect(changes.at(-1).state).toBe("stopped");
});
