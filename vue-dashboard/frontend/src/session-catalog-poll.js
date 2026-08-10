// Pacing policy for the background session-catalog poll.
//
// Kept as pure functions (no Vue, no timers) so the cadence decision is
// testable on its own — the composable in composables/useSessionCatalog.js
// only turns the number this module returns into a setTimeout.

/** Lifecycles the server is expected to move on its own within seconds. */
export const TRANSITIONAL_LIFECYCLES = Object.freeze(["Starting", "Ending"]);

/** Lifecycles that change without any operator action (runtime/watchdog driven). */
export const LIVE_LIFECYCLES = Object.freeze(["Active", "Starting", "Ending"]);

export const FAST_POLL_MS = 2000;
export const LIVE_POLL_MS = 5000;
export const IDLE_POLL_MS = 15000;
export const MAX_BACKOFF_MS = 60000;

export function hasLifecycle(sessions, lifecycles) {
  if (!Array.isArray(sessions)) return false;
  return sessions.some((session) => lifecycles.includes(session?.lifecycle));
}

/**
 * Decide how long to wait before the next background catalog read.
 *
 * @param {object}  options
 * @param {Array}   options.sessions       Current normalized catalog rows.
 * @param {boolean} options.hidden         True when the tab is backgrounded.
 * @param {number}  options.consecutiveFailures  Failed polls since the last good read.
 * @returns {number|null} Milliseconds to wait, or null to stop polling entirely.
 *
 * TODO(you): implement the adaptive cadence. See the notes in the chat — the
 * trade-off is request volume against how long an operator stares at a stale
 * row. The constants above are available; `hasLifecycle(sessions, ...)` tells
 * you whether anything is mid-transition or otherwise server-driven.
 *
 * Baseline below is deliberately dumb: one fixed interval, no backoff, no
 * hidden-tab handling. It works, but it polls a room full of resting rows just
 * as hard as a rack mid-start.
 */
export function nextPollDelay({ sessions = [], hidden = false, consecutiveFailures = 0 } = {}) {
  return LIVE_POLL_MS;
}
