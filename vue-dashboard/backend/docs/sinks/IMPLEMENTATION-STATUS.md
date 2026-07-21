# All-sink support — implementation status & handoff

Snapshot of the multi-agent execution of `docs/sinks/*`. Nothing is committed —
all work is uncommitted working-tree changes (git is coordinated by the human).

## Progress: 35 / 35 packets complete

**Done (35):** 00A, 00, 01, 02, 03, 04, 05, 06, 07, 08, 09, 09A, 10, 11, 12, 13,
14, 15, 16, 17, 18, 19, 20, 21, 22, 22A, 23, 24, 25, 26, 27, 28, 29, 30, 31.

**In flight:** none.  
**Not started:** none.

All-sink packet graph is complete. Remaining work is integrator follow-ups and
pre-existing non-sink suite drift (below).

## Integrator follow-ups (not packet-scoped)

1. Wire `RuntimeContext.plot_transport` / `plot_transport_factory` in
   `morelia.py` so live acquisition publishes into `PlotBroker`.
2. HTTP plot-token mint (or status payload tokens) for Vue without
   `VITE_PLOT_STREAM_TOKEN`.
3. Repair `device_templates.get_by_id` / `tests/test_device_templates.py`
   collection ImportError.
4. Triage 44 full-suite failures (CLI device-template / config-validate /
   runtime-cmd / watch / host-supervision / multi-device lease).
5. Capture Pod8206HR/Pod8401HR multi-sink `sink_matrix` hardware evidence.

## This session's packet closeouts

| Packet | Verification |
|---|---|
| **27** backend-plot-transport | plot + events SSE + sink factory → **48 passed**; factory reconciled (PLOT builds) |
| **28** vue-live-plot | `plot-stream.test.js` → **9 passed**; `npm run build` OK |
| **30** cross-sink-release-gates | multi_sink_runtime + service_sink_outages → **11 passed**; broad suite **958 passed / 44 failed** (pre-existing) |
| **31** rollout-documentation | support-matrix + operator-runbook; arch/impl/audit overlays; contract tests → **45 passed** |

## Key artifacts

- [`docs/sinks/support-matrix.md`](support-matrix.md)
- [`docs/sinks/operator-runbook.md`](operator-runbook.md)
- Backend Plot: `app/output/plot_sink.py`, `app/api/plot_stream.py`
- Vue Plot: `frontend/src/plot-stream.js`, `frontend/src/components/LivePlot.vue`
- Release gates: `tests/test_multi_sink_runtime.py`,
  `tests/test_service_sink_outages.py`

## Notes carried for ops

- Finalizer uses `finalized_at` as lease heartbeat; `artifact_state=='merged'` is
  done-signal.
- EDF mid-record interrupt zero-pads; PVFS merge uses child process on Windows.
- Sink errors use picklable `_SinkErrorSender`; per-sink failures ride
  `payload["sinks"]`, not `devices`.
- Plot SSE off OpenAPI; broker in `app.extensions["plot_broker"]`.
- Stop completes acquisition; later start = new identities even if merge pending.
