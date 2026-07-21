"""Watchdog process package.

The watchdog process is the standalone process (not the Flask control-plane
app) that will own Morelia, DataFlow, DataFlow stream workers, and sinks, and
report telemetry directly to the control plane. This packet only adds the
local SQLite outbox (see ``outbox.py``); the process entrypoint itself lands
in a later packet.
"""
