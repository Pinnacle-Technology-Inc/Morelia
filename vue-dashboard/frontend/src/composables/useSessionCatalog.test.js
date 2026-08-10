import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useSessionCatalog } from "./useSessionCatalog";

const rows = (...names) => names.map((name, index) => ({ id: String(index), name, lifecycle: "Active" }));
const live = (sessions) => ({ sessions, state: "live", error: "" });

/** Minimal `document`-alike so the composable can be driven without a DOM. */
function fakeVisibility(initial = "visible") {
  const listeners = new Set();
  return {
    visibilityState: initial,
    addEventListener: (_type, fn) => listeners.add(fn),
    removeEventListener: (_type, fn) => listeners.delete(fn),
    set(state) {
      this.visibilityState = state;
      for (const fn of listeners) fn();
    },
  };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it("re-reads the catalog on a timer without an explicit refresh", async () => {
  const load = vi.fn()
    .mockResolvedValueOnce(live(rows("preparing")))
    .mockResolvedValue(live(rows("preparing", "started")));
  const catalog = useSessionCatalog({ load, visibility: fakeVisibility() });

  catalog.start();
  await vi.advanceTimersByTimeAsync(0);
  expect(catalog.sessions.value).toHaveLength(1);

  await vi.advanceTimersByTimeAsync(30000);
  expect(load.mock.calls.length).toBeGreaterThan(1);
  expect(catalog.sessions.value).toHaveLength(2);

  catalog.stop();
});

it("never shows the loading placeholder during a background poll", async () => {
  const states = [];
  const load = vi.fn().mockResolvedValue(live(rows("one")));
  const catalog = useSessionCatalog({ load, visibility: fakeVisibility() });

  catalog.start();
  await vi.advanceTimersByTimeAsync(0);

  // Only foreground reads may blank the page; record every state a poll produces.
  for (let tick = 0; tick < 3; tick += 1) {
    await vi.advanceTimersByTimeAsync(30000);
    states.push(catalog.state.value);
  }
  expect(states).not.toContain("loading");

  catalog.stop();
});

it("keeps the last good list when a background poll fails", async () => {
  const load = vi.fn()
    .mockResolvedValueOnce(live(rows("one", "two")))
    .mockRejectedValue(new Error("backend offline"));
  const catalog = useSessionCatalog({ load, visibility: fakeVisibility() });

  catalog.start();
  await vi.advanceTimersByTimeAsync(0);
  await vi.advanceTimersByTimeAsync(30000);

  expect(catalog.sessions.value).toHaveLength(2);
  expect(catalog.error.value).toBe("backend offline");

  catalog.stop();
});

it("blanks the list when a foreground read fails", async () => {
  const load = vi.fn().mockRejectedValue(new Error("backend offline"));
  const catalog = useSessionCatalog({ load, visibility: fakeVisibility() });

  catalog.start();
  await vi.advanceTimersByTimeAsync(0);

  expect(catalog.sessions.value).toEqual([]);
  expect(catalog.state.value).toBe("unavailable");

  catalog.stop();
});

it("does not stack overlapping reads", async () => {
  let release;
  const load = vi.fn(() => new Promise((resolve) => { release = () => resolve(live(rows("one"))); }));
  const catalog = useSessionCatalog({ load, visibility: fakeVisibility() });

  catalog.start();
  catalog.refresh({ silent: true });
  catalog.refresh({ silent: true });
  expect(load).toHaveBeenCalledTimes(1);

  release();
  await vi.advanceTimersByTimeAsync(0);
  catalog.stop();
});

it("re-reads immediately when a hidden tab becomes visible again", async () => {
  const load = vi.fn().mockResolvedValue(live(rows("one")));
  const visibility = fakeVisibility();
  const catalog = useSessionCatalog({ load, visibility });

  catalog.start();
  await vi.advanceTimersByTimeAsync(0);
  const afterMount = load.mock.calls.length;

  visibility.set("hidden");
  visibility.set("visible");
  await vi.advanceTimersByTimeAsync(0);

  expect(load.mock.calls.length).toBeGreaterThan(afterMount);
  catalog.stop();
});

it("drops a response that lands after stop()", async () => {
  let release;
  const load = vi.fn(() => new Promise((resolve) => { release = () => resolve(live(rows("late"))); }));
  const catalog = useSessionCatalog({ load, visibility: fakeVisibility() });

  catalog.start();
  catalog.stop();
  release();
  await vi.advanceTimersByTimeAsync(0);

  expect(catalog.sessions.value).toEqual([]);
});
