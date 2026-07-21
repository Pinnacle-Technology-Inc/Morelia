"""Control-plane process management.

``app/control/`` is the daemon's south-side process manager: it spawns,
stops, and reattaches Dataflow Runtime Host children, keeping one live
host per dataflow and persisting host identity (port + token) to the
``sessions`` table so a restarted daemon can reconnect without spawning
duplicates (Slice 7 — reconcile).
"""
