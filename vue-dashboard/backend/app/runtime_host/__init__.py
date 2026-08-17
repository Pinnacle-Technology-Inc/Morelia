"""The Dataflow Runtime Host package — one process per dataflow.

A Dataflow Runtime Host:
- Loads an immutable ``Manifest`` describing its one dataflow and device→sink pairs.
- Owns one ``WatchdogProcessDriver``, fronted by a ``LifecycleSafetyGate``.
- Serves ``POST /api/v1/commands`` + ``GET /status`` on a loopback-only HTTP port so the
  control-plane daemon can drive it.

"""
