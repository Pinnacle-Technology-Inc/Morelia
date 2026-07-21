"""The Dataflow Runtime Host package — one process per dataflow.

A Dataflow Runtime Host:
- Loads an immutable ``Manifest`` describing its one dataflow and device→sink pairs.
- Owns exactly one ``RuntimeControlDriver`` (the Morelia driver), fronted by a
  ``LifecycleSafetyGate``.
- Serves ``POST /api/v1/commands`` + ``GET /status`` on a loopback-only HTTP port so the
  control-plane daemon (Stage 2.3) can drive it.

One host per dataflow, always. Never two.
"""
