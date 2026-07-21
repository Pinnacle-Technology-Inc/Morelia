"""The fault menu: a fixed, physical set of things you DO to real hardware.

This module is the answer to "I'm not good at enumerating failure cases." You
don't enumerate them. You apply this short, reusable menu of physical faults to
the real running system and record what happens. The taxonomy is bounded
because it is physical, not imaginative:

    kill_mid_report      — hard-kill the watchdog child between emit and push
    respawn              — stop + spawn; capture BOTH watchdog identities
    double_send          — replay one captured envelope twice
    counter_reset        — respawn so the child's report_id/sequence resets
    plane_outage         — bring ingest down, then back, during a stream

Each function operates on the REAL ``HostSupervisor`` and a REAL session. None
of them fake anything — a kill is ``proc.kill()``, a respawn is a real second
subprocess. The oracle for "was the outcome correct?" lives in
``expected_after_respawn`` (below), which you own.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.control.supervisor import HostSupervisor
from app.models.session import Session


@dataclass(frozen=True)
class WatchdogIdentity:
    """The identity of one watchdog process instance, captured at spawn time."""

    runtime_id: str
    watchdog_id: str | None
    pid: int | None
    port: int


def current_identity(supervisor: HostSupervisor, session: Session) -> WatchdogIdentity:
    """Read the live identity the supervisor is tracking for this dataflow."""
    status = supervisor._probe_status(  # noqa: SLF001 - harness reaches into the real probe
        _port_of(supervisor, session)
    )
    return WatchdogIdentity(
        runtime_id=str(status.get("runtime_id", "")),
        watchdog_id=status.get("watchdog_id"),
        pid=status.get("pid"),
        port=_port_of(supervisor, session),
    )


def kill_mid_report(supervisor: HostSupervisor, session: Session) -> WatchdogIdentity:
    """Hard-kill the watchdog child WITHOUT the graceful stop path.

    This is the fault behind your own commit "child process being hard killed
    before it can report back stopped status": no ``stop`` command, no drain —
    just ``proc.kill()``. On Windows ``kill()`` maps to TerminateProcess, the
    same hard kill ``proc.terminate()`` uses, so this reproduces the real
    daemon-crash / lease-expiry path rather than a clean shutdown.

    Returns the identity that was killed, so the caller can assert that a report
    still in flight from THIS identity is fenced out after a respawn.
    """
    identity = current_identity(supervisor, session)
    entry = supervisor._children[session.dataflow_id]  # noqa: SLF001 - harness
    if entry.proc is not None:
        entry.proc.kill()
        entry.proc.wait(timeout=5)
    return identity


def respawn(supervisor: HostSupervisor, session: Session) -> tuple[WatchdogIdentity, WatchdogIdentity]:
    """Kill the current watchdog and spawn a fresh one for the same dataflow.

    Returns ``(old_identity, new_identity)``. The whole point of packet 3 is
    that the plane must reject late telemetry stamped with ``old_identity`` once
    ``new_identity`` is the active one — this hands you both so the assertion is
    exact, not "some id changed".
    """
    old = kill_mid_report(supervisor, session)
    # The supervisor still has the (now-dead) child in its registry; drop it so
    # spawn() does not raise HostAlreadyRunning, mirroring what reconcile()/stop
    # would have done in the real daemon.
    supervisor._children.pop(session.dataflow_id, None)  # noqa: SLF001 - harness
    supervisor.spawn(session)
    new = current_identity(supervisor, session)
    return old, new


# ─────────────────────────────────────────────────────────────────────────────
# YOUR CONTRIBUTION — the respawn oracle (the one real decision in packet 3)
# ─────────────────────────────────────────────────────────────────────────────
#
# After a respawn, the plane will have received reports from BOTH the old and
# the new watchdog identity. This function is the oracle: given every envelope
# that was captured across the respawn, it returns the set of report_ids that
# SHOULD each have exactly one backend_events row. The replay test compares the
# real table against whatever you return here.
#
# This encodes the packet-3 dedupe-key decision that nothing else in the repo
# has settled yet. There are two candidate rules, and only you can pick, because
# it depends on how Morelia mints report_id:
#
#   (A) report_id is globally unique (e.g. a UUID per report). Then the dedupe
#       key is report_id ALONE, and two identities never collide.
#
#   (B) report_id is a per-process counter that RESETS to 0/1 on every watchdog
#       spawn. Then old watchdog's report_id=1 and new watchdog's report_id=1
#       are DIFFERENT events, and the dedupe key must be COMPOSITE
#       (watchdog_id, report_id) — otherwise the new watchdog's first report is
#       silently absorbed as a "duplicate" and its telemetry vanishes.
#
# Look at how Morelia actually generates the id in the vendored Watchdog/ code,
# then implement the ~5-10 lines below to match reality. Return a set of the
# keys you expect to be distinct rows.
#
# `envelopes` is a list of parsed envelope dicts (each is
# {"protocol_version": "1", "report": {... "report_id":..., "watchdog_id":...}}).


def expected_after_respawn(envelopes: list[dict]) -> set:
    """Return the set of dedupe-keys that should each map to one distinct row.

    TODO(you): implement per rule (A) or (B) above, based on how Morelia mints
    report_id. For (A) return the set of report_ids. For (B) return the set of
    (watchdog_id, report_id) tuples.
    """
    raise NotImplementedError(
        "Decide the packet-3 dedupe key (report_id alone vs (watchdog_id, "
        "report_id)) from how Morelia mints report_id, then implement this."
    )


# ── internal ──────────────────────────────────────────────────────────────────


def _port_of(supervisor: HostSupervisor, session: Session) -> int:
    return supervisor._children[session.dataflow_id].port  # noqa: SLF001 - harness
