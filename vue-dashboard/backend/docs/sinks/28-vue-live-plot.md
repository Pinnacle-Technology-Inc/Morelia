# Packet 28 — Render the Vue live Plot

Status: complete  
Size: M  
Depends on: 22, 27

## Purpose

Give dashboard users a live browser plot for configured Plot sinks, including connection, lag, drop, and sink-health feedback.

## Prior state

The frontend session detail page uses mock/static sink data and has no live plot client or bounded rendering buffer.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “Plot”, “API/session services”, and release-critical scenario 5.
- `C:/Users/ahoang/vue-dashboard/frontend/src/pages/SessionDetailPage.vue` — current session/sink presentation.
- `C:/Users/ahoang/vue-dashboard/frontend/src/operations-api.js` — API client conventions.
- `C:/Users/ahoang/vue-dashboard/frontend/src/data.js` — mock sink shape to retire/translate.
- `C:/Users/ahoang/vue-dashboard/frontend/src/App.vue` — route/page wiring.
- `C:/Users/ahoang/vue-dashboard/frontend/package.json` — Vue/Vite/Vitest commands and dependencies.

## Exact edit set

- `C:/Users/ahoang/vue-dashboard/frontend/src/plot-stream.js`
- `C:/Users/ahoang/vue-dashboard/frontend/src/plot-stream.test.js`
- `C:/Users/ahoang/vue-dashboard/frontend/src/components/LivePlot.vue`
- `C:/Users/ahoang/vue-dashboard/frontend/src/pages/SessionDetailPage.vue`

## Scope boundaries

This packet changes the sibling frontend repository. Do not add desktop Plot dependencies, persist samples, hide server-reported drops, or redesign unrelated session pages.

## Contract / invariant

The browser holds a bounded rolling window, reconnects using the server cursor contract, discards stale subscriptions when navigation changes, and presents sink state separately from source state.

## Acceptance criteria

1. A configured Plot sink renders ordered live samples with responsive axes/channel labels and no unbounded DOM or memory growth.
2. Connecting, reconnecting, stale, degraded, dropped-sample, unauthorized, and stopped states are visibly distinct and accessible.
3. Navigating away/unmounting closes the stream and timers; reconnect cannot append data from a prior session/sink.

## Verification

```powershell
Push-Location C:\Users\ahoang\vue-dashboard\frontend
npm test -- src/plot-stream.test.js
npm run build
Pop-Location
```

## Failure handling

On transport/render error, stop retries at the documented bound, preserve the last frame as stale, show the sink-specific cause, and offer a manual reconnect.

## Handoff note

Record browser compatibility, maximum rendered points, reconnect behavior, and screenshots/manual test notes for packet 30.

### Packet 28 closeout (for packet 30)

- Browser: native `EventSource` (Chromium/Firefox/Safari). No polyfill; missing
  EventSource surfaces as an explicit error state.
- Max rendered points: `MAX_RENDERED_POINTS = 2000` (rolling window in
  `frontend/src/plot-stream.js`).
- Reconnect: up to `MAX_RECONNECT_ATTEMPTS = 5` with exponential backoff from
  500 ms (capped at 8 s), always using `?after=<lastSeq>`; then **Stale** (keeps
  last frame) or **Error**, with a manual Reconnect control.
- Distinct UI states: connecting, live, reconnecting, stale, degraded, dropped
  samples, unauthorized, stopped, error — separate from source `StatusBadge`.
- Auth: token via LivePlot `token` prop, `token()` resolver, or
  `VITE_PLOT_STREAM_TOKEN`. No HTTP mint endpoint yet — without a token the
  panel shows **Unauthorized** (expected until an integrator adds minting).
- Unmount/navigation: `onBeforeUnmount` disconnects EventSource and timers;
  `retarget` clears the sample window so a prior session/sink cannot append.
- Verification: `npm test -- src/plot-stream.test.js` → **9 passed**;
  `npm run build` → OK.
