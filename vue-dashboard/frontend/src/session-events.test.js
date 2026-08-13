import { afterEach, expect, it, vi } from "vitest";
import {
  buildSessionEventsUrl,
  createSessionEventStream,
  isSessionActivityEvent,
} from "./session-events";

afterEach(() => vi.useRealTimers());

class FakeEventSource {
  static instances = [];
  constructor(url) { this.url = url; this.listeners = {}; FakeEventSource.instances.push(this); }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  emit(type, data, id) {
    const handler = type === "message" ? this.onmessage : this.listeners[type];
    handler?.({ type, data: JSON.stringify(data), lastEventId: String(id) });
  }
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

it("subscribes to named Activity notifications without classifying runtime replay as Activity", () => {
  const stream = createSessionEventStream({ sessionId: 7, EventSourceImpl: FakeEventSource });
  stream.start();
  const source = FakeEventSource.instances.at(-1);

  source.emit("runtime.report", { session_id: 7, sequence: 1 }, 10);
  source.emit("activity.recorded", { session_id: 7, activity: { kind: "issue.opened" } }, 11);
  source.emit("gap.recorded", { session_id: 7, activity: { kind: "gap.recorded" } }, 12);

  const events = stream.getSnapshot().events;
  expect(events.map((event) => event.type)).toEqual([
    "runtime.report",
    "activity.recorded",
    "gap.recorded",
  ]);
  expect(events.filter(isSessionActivityEvent).map((event) => event.id)).toEqual(["11", "12"]);
  expect(isSessionActivityEvent(events[0])).toBe(false);
});
