import { getCurrentInstance, onBeforeUnmount, onMounted, ref } from "vue";
import { loadSessionCatalog } from "../session-api";
import { nextPollDelay } from "../session-catalog-poll";

/**
 * Keep the session catalog live.
 *
 * Same shape App.vue used to hold inline (`sessions` / `state` / `error`), but
 * the list now re-reads itself on a timer instead of only on navigation. Three
 * properties matter and none of them are optional:
 *
 * - **Silent background reads.** A poll must never flip `state` to "loading";
 *   Overview and Sessions both render a whole-page placeholder on that value,
 *   so a naive `setInterval(refresh)` would strobe the list every tick.
 * - **Last-good-wins on a failed poll.** One blipped request must not empty an
 *   operator's overview mid-run. Same call as SessionDetailPage.refreshDetail().
 * - **No overlapping reads.** loadSessionCatalog() fires two requests; a slow
 *   backend plus a short interval otherwise stacks them and lets an older
 *   response land after a newer one.
 *
 * @param {object}   options
 * @param {Function} options.load  Injectable catalog loader (tests pass a fake).
 * @param {object}   options.visibility  Injectable `document`-like visibility source.
 */
export function useSessionCatalog({
  load = loadSessionCatalog,
  visibility = typeof document === "undefined" ? null : document,
} = {}) {
  const sessions = ref([]);
  const state = ref("loading");
  const error = ref("");
  const lastUpdatedAt = ref(null);

  let timer = null;
  let inFlight = false;
  let stopped = false;
  let consecutiveFailures = 0;
  // Bumped on teardown so a response that lands after unmount is dropped
  // instead of writing into refs nobody is rendering any more.
  let generation = 0;

  function isHidden() {
    return visibility?.visibilityState === "hidden";
  }

  function clearTimer() {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  }

  function schedule() {
    clearTimer();
    if (stopped) return;
    const delay = nextPollDelay({
      sessions: sessions.value,
      hidden: isHidden(),
      consecutiveFailures,
    });
    // A null delay means "stop polling" — the tab is hidden or we have given
    // up. Nothing re-arms the timer until refresh() is called again, which
    // the visibilitychange handler below does on the way back to visible.
    if (delay == null) return;
    timer = setTimeout(() => {
      timer = null;
      refresh({ silent: true });
    }, delay);
  }

  /**
   * Re-read the catalog.
   * @param {boolean} silent  Background read: keep the current list and state
   *   on screen instead of showing the loading placeholder.
   */
  async function refresh({ silent = false } = {}) {
    // A read is already in flight. Its `finally` re-arms the timer, so the
    // caller's intent — see fresh data soon — is already satisfied.
    if (inFlight) return;
    inFlight = true;
    const mine = generation;
    if (!silent) {
      state.value = "loading";
      error.value = "";
    }
    try {
      const catalog = await load();
      if (mine !== generation) return;
      sessions.value = catalog.sessions;
      state.value = catalog.state;
      error.value = catalog.error;
      lastUpdatedAt.value = Date.now();
      consecutiveFailures = 0;
    } catch (err) {
      if (mine !== generation) return;
      consecutiveFailures += 1;
      const message = err instanceof Error ? err.message : "Could not load sessions.";
      error.value = message;
      // Foreground reads (mount, Retry, post-mutation) own the screen and may
      // legitimately blank it. Background polls keep the last good list: mild
      // staleness beats an empty overview during a transient backend hiccup.
      if (!silent) {
        sessions.value = [];
        state.value = "unavailable";
      } else if (!sessions.value.length) {
        state.value = "unavailable";
      }
    } finally {
      inFlight = false;
      if (mine === generation) schedule();
    }
  }

  function onVisibilityChange() {
    if (isHidden()) {
      clearTimer();
      return;
    }
    // Coming back to a backgrounded tab is exactly when the list is most
    // stale, so read immediately rather than waiting out an interval.
    refresh({ silent: true });
  }

  function start() {
    stopped = false;
    visibility?.addEventListener?.("visibilitychange", onVisibilityChange);
    refresh();
  }

  function stop() {
    stopped = true;
    generation += 1;
    clearTimer();
    visibility?.removeEventListener?.("visibilitychange", onVisibilityChange);
  }

  // Auto-wire the lifecycle only when there is a component to wire it to;
  // tests drive start()/stop() directly.
  if (getCurrentInstance()) {
    onMounted(start);
    onBeforeUnmount(stop);
  }

  return { sessions, state, error, lastUpdatedAt, refresh, start, stop };
}
