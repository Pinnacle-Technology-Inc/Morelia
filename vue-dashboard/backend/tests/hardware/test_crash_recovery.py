"""Crash-recovery judges: assert packets 4/6/8/9's promises from real crash runs.

Each test judges one ``checkpoint.py --kill <layer>`` run from three durable
evidence sources — no timing assertions, no re-derivation:

    - ``fixtures/latest_run_meta.json``  what the checkpoint did and observed
    - ``fixtures/latest_capture.jsonl``  what crossed the wire (+ the plane's
      own 202/409 verdicts at the moment of delivery)
    - ``instance/guarded-experiment.sqlite3``  what the control plane made
      durable (events, ownership, operations, sessions, claims)

Run order:
    venv\\Scripts\\python.exe -m tests.hardware.checkpoint --template <t> --kill watchdog
    RUN_HARDWARE=1 pytest tests/hardware/test_crash_recovery.py -v
(repeat per layer: host / plane / stop-race)

A test SKIPs when the last run wasn't its layer; it FAILs when the run was and
the spec's promise didn't hold — that failure is the finding.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from tests.hardware.capture import load_captures

FIXTURES = Path(__file__).parent / "fixtures"
META_FILE = FIXTURES / "latest_run_meta.json"
CAPTURE_FILE = FIXTURES / "latest_capture.jsonl"
DEV_DB = Path(__file__).resolve().parents[2] / "instance" / "guarded-experiment.sqlite3"


# ── evidence fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def meta() -> dict:
    if not META_FILE.exists():
        pytest.skip("no run metadata — run checkpoint.py with a --kill mode first")
    return json.loads(META_FILE.read_text(encoding="utf-8"))


@pytest.fixture
def wire() -> list[tuple[dict, int | None, str | None]]:
    """(flat_envelope, http_status, iso_ts) for every captured packet-5 report."""
    out = []
    for cap in load_captures(CAPTURE_FILE):
        try:
            env = json.loads(cap.get("raw", ""))
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(env, dict) and "report_id" in env:
            out.append((env, cap.get("status"), cap.get("ts")))
    return out


@pytest.fixture
def db():
    if not DEV_DB.exists():
        pytest.skip(f"dev database not found at {DEV_DB}")
    con = sqlite3.connect(f"file:{DEV_DB}?mode=ro", uri=True)
    yield con
    con.close()


def _require_mode(meta: dict, mode: str, *required_keys: str) -> None:
    if meta.get("mode") != mode:
        pytest.skip(f"last run was mode={meta.get('mode')!r}; run checkpoint --kill {mode}")
    missing = [key for key in required_keys if key not in meta]
    if missing:
        pytest.skip(
            f"checkpoint run aborted before the fault was injected (meta lacks "
            f"{missing}) — re-run checkpoint --kill {mode}"
        )


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _counter(report_id: str) -> int:
    """report_id format is '<watchdog_id>:<counter>' (verified on hardware)."""
    return int(report_id.rsplit(":", 1)[1])


def _no_duplicate_report_ids(db, dataflow_id: str) -> None:
    total, distinct = db.execute(
        "SELECT COUNT(report_id), COUNT(DISTINCT report_id) FROM backend_events "
        "WHERE dataflow_id=? AND report_id IS NOT NULL",
        (dataflow_id,),
    ).fetchone()
    assert total == distinct, f"duplicate report_ids persisted: {total} rows, {distinct} distinct"


# ── Layer 3: watchdog crash → packet-8 respawn ────────────────────────────────

def test_watchdog_crash_respawns_new_identity_that_streams(meta, wire, db):
    """Packet 8: after a hard watchdog kill, a NEW watchdog_id must appear under
    the same runtime_id, be accepted by the plane (202), and actually stream."""
    _require_mode(meta, "watchdog", "watchdog_killed_at")
    wd_a = meta.get("watchdog_a")
    wd_b = meta.get("watchdog_b")

    assert wd_b, (
        "respawn never produced a live replacement watchdog — packet 8 does not "
        "survive a real crash on this rig. Read the host log printed by the "
        "checkpoint, then the ged-watchdog-*.log it names, for the replacement's "
        "actual preflight traceback. Known causes: the killed watchdog's output "
        "files blocking exclusive create (fixed by resume-append), or its orphaned "
        "Morelia queue_server children still holding the COM ports. "
        f"(killed watchdog_a={wd_a!r})"
    )
    assert wd_b != wd_a, "respawn reused the dead watchdog_id — identity must rotate"

    accepted_b = [env for env, status, _ts_ in wire if env["watchdog_id"] == wd_b and status == 202]
    assert accepted_b, (
        f"respawned watchdog {wd_b[:8]} was never accepted by the plane — identity "
        "rotation (set_watchdog sync) did not reach runtime_ownerships before its reports"
    )

    # Same runtime_id across the rotation, per the packet-8 contract line.
    runtimes = {env["runtime_id"] for env, _s, _t in wire if env["watchdog_id"] in (wd_a, wd_b)}
    assert len(runtimes) == 1, f"respawn changed runtime_id: {runtimes}"

    _no_duplicate_report_ids(db, meta["dataflow_id"])


# ── Layer 2: runtime_host crash → direct-ingest continuity + adoption ─────────

def test_host_crash_telemetry_continues_and_watchdog_adopted(meta, wire, db):
    """Packet 6: telemetry must keep landing while the host is dead (the watchdog
    posts directly), and the replacement host must ADOPT the live watchdog."""
    _require_mode(meta, "host", "host_killed_at", "orphan_window_end")
    killed_at = _ts(meta["host_killed_at"])
    window_end = _ts(meta["orphan_window_end"])

    during_outage = [
        env for env, status, ts in wire
        if status == 202 and ts and killed_at < _ts(ts) < window_end
    ]
    assert during_outage, (
        "no report was accepted while the runtime_host was dead — direct ingest "
        "did not keep telemetry flowing through a host outage"
    )

    assert meta.get("host_respawned"), "reconcile() did not produce a replacement host"
    assert meta.get("watchdog_after") == meta.get("watchdog_before"), (
        f"replacement host did not adopt the live watchdog: before="
        f"{meta.get('watchdog_before')!r} after={meta.get('watchdog_after')!r} "
        "(packet 6: adopt a live, identity-matching watchdog; only respawn when it's gone)"
    )
    assert meta.get("watchdog_state_after") == "adopted", (
        f"expected watchdog_state 'adopted', got {meta.get('watchdog_state_after')!r}"
    )

    _no_duplicate_report_ids(db, meta["dataflow_id"])


# ── Layer 1: control-plane outage → packet-4 outbox exactly-once ──────────────

def test_plane_outage_outbox_delivers_exactly_once(meta, wire, db):
    """Packet 4: reports emitted while the plane was DOWN must all arrive after
    recovery — per-watchdog counters contiguous (nothing lost), no duplicates."""
    _require_mode(meta, "plane", "outage_start", "outage_end")
    outage_start, outage_end = _ts(meta["outage_start"]), _ts(meta["outage_end"])

    # The blackout was real: nothing could be captured while the server was down.
    in_blackout = [ts for _e, _s, ts in wire if ts and outage_start < _ts(ts) < outage_end]
    assert not in_blackout, "capture shows deliveries during the outage — plane never went down?"

    # Recovery was real: deliveries resumed after the plane came back.
    after = [env for env, status, ts in wire if status == 202 and ts and _ts(ts) > outage_end]
    assert after, "no deliveries after the plane came back — outbox flush never happened"

    # Exactly-once, the durable way: for each watchdog, the persisted counters
    # form a contiguous run — a gap = a report emitted during the outage that
    # never arrived; a duplicate = re-delivery that dedup failed to absorb.
    rows = db.execute(
        "SELECT watchdog_id, report_id FROM backend_events "
        "WHERE dataflow_id=? AND report_id IS NOT NULL",
        (meta["dataflow_id"],),
    ).fetchall()
    assert rows, "no identity-stamped events persisted for this run"
    by_watchdog: dict[str, list[int]] = {}
    for watchdog_id, report_id in rows:
        by_watchdog.setdefault(watchdog_id, []).append(_counter(report_id))
    for watchdog_id, counters in by_watchdog.items():
        counters.sort()
        expected = list(range(counters[0], counters[-1] + 1))
        assert counters == expected, (
            f"watchdog {watchdog_id[:8]}: counters not contiguous — "
            f"missing {sorted(set(expected) - set(counters))} "
            "(reports spooled during the outage were lost)"
        )

    _no_duplicate_report_ids(db, meta["dataflow_id"])


# ── Packet 9: crash during stop → no false completion ─────────────────────────

def test_stop_race_never_fakes_a_clean_stop(meta, db):
    """Packet 9: with watchdog+host dead and no stop proof, the session must stay
    ACTIVE (retryable), the stop operation FAILED/UNCERTAIN, and claims held."""
    _require_mode(meta, "stop-race", "killed_at", "stop_result")
    session_id = meta["session_id"]

    assert meta.get("stop_result") != "completed", (
        "stop_managed reported a CLEAN stop with no possible proof — packet 9 violated"
    )
    assert meta.get("stop_result") == "StopProofMissing", (
        f"expected StopProofMissing, got {meta.get('stop_result')!r}"
    )

    (status,) = db.execute(
        "SELECT status FROM sessions WHERE id=?", (session_id,)
    ).fetchone()
    assert str(status).lower() == "active", (
        f"session should stay ACTIVE (retryable) without stop proof, is {status!r}"
    )

    row = db.execute(
        "SELECT state FROM operations WHERE session_id=? AND command='stop' "
        "ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    assert row is not None, "no stop operation recorded"
    assert str(row[0]).lower() in ("failed", "uncertain"), (
        f"stop operation should be failed/uncertain, is {row[0]!r}"
    )

    claims = db.execute(
        "SELECT id, claim_state FROM device_configs WHERE claimed_session_id=?",
        (session_id,),
    ).fetchall()
    assert claims and all(str(c[1]).lower() == "claimed" for c in claims), (
        f"device claims were released without stop proof: {claims} "
        "(packet 9: claims released only after clean proof)"
    )


# ══ Recovery decision matrix (WatchdogRecoveryCoordinator) ════════════════════
#
#   Evidence                                        Recovery action
#   host dead, watchdog absent, leases free      -> start fresh          (row 1)
#   host dead, watchdog authenticates            -> adopt + rebind       (row 2)
#   watchdog authenticates, adoption fails       -> stop exact -> fresh  (row 3)
#   evidence conflicts / times out               -> RECOVERING + backoff (row 4)


def _recovery_details(snapshot: dict | None) -> dict:
    return ((snapshot or {}).get("details") or {}).get("recovery") or {}


def test_recover_fresh_when_watchdog_absent_and_leases_free(meta, wire, db):
    """Row 1: with the watchdog dead (leases auto-released), the coordinator
    must START_FRESH — a new watchdog under a NEW runtime, and it streams."""
    _require_mode(meta, "recover-fresh", "killed_at")
    wd_a, wd_b = meta.get("watchdog_a"), meta.get("watchdog_b")

    assert wd_b, (
        "no fresh watchdog came up after START_FRESH — recovery deferred instead. "
        f"old ownership after reconcile: {meta.get('old_ownership_after')} "
        "(if reason is fresh_watchdog_start_failed, the dead watchdog's leftovers — "
        "orphaned queue_servers / output files — blocked the fresh start: real finding)"
    )
    assert wd_b != wd_a, "START_FRESH must mint a new watchdog identity"
    assert meta.get("new_runtime_id") and meta["new_runtime_id"] != meta.get("runtime_id"), (
        "START_FRESH goes through spawn(), which mints a new runtime_id — the old "
        "one must not be reused"
    )

    accepted_fresh = [e for e, s, _t in wire if e["watchdog_id"] == wd_b and s == 202]
    assert accepted_fresh, "fresh watchdog never streamed an accepted report"

    old_after = meta.get("old_ownership_after") or {}
    assert old_after.get("state") == "stopped", (
        f"dead runtime's ownership should be terminal 'stopped', is {old_after.get('state')!r}"
    )
    _no_duplicate_report_ids(db, meta["dataflow_id"])


def test_recover_adopt_rebinds_live_watchdog(meta, wire, db):
    """Row 2: an authenticated, identity-verified watchdog must be ADOPTED — same
    watchdog_id rebound to the replacement host, telemetry never lost."""
    _require_mode(meta, "recover-adopt", "host_killed_at", "orphan_window_end")
    wd = meta.get("watchdog_before")

    # Telemetry kept landing while the host was dead (direct ingest).
    killed_at, window_end = _ts(meta["host_killed_at"]), _ts(meta["orphan_window_end"])
    during = [e for e, s, ts in wire if s == 202 and ts and killed_at < _ts(ts) < window_end]
    assert during, "no accepted report while the host was dead — direct ingest broke"

    # Same watchdog identity survived, rebound to a NEW runtime.
    assert meta.get("watchdog_after") == wd, (
        f"coordinator did not adopt the live watchdog: before={wd!r} "
        f"after={meta.get('watchdog_after')!r}"
    )
    assert meta.get("new_runtime_id") and meta["new_runtime_id"] != meta.get("runtime_id"), (
        "adoption rebinds the watchdog to a REPLACEMENT host (new runtime_id)"
    )
    rebound = [
        e for e, s, _t in wire
        if s == 202 and e["watchdog_id"] == wd and e["runtime_id"] == meta["new_runtime_id"]
    ]
    assert rebound, (
        "no accepted report carries the adopted watchdog under the new runtime_id — "
        "the rebind never took effect on the wire"
    )

    old_after = meta.get("old_ownership_after") or {}
    assert old_after.get("state") == "stopped", (
        f"old runtime's ownership should be 'stopped' after handover, is {old_after.get('state')!r}"
    )

    # Continuity: the same watchdog's counters must be contiguous across the
    # whole crash + adoption — nothing dropped during the handover.
    rows = db.execute(
        "SELECT report_id FROM backend_events WHERE dataflow_id=? AND watchdog_id=?",
        (meta["dataflow_id"], wd),
    ).fetchall()
    counters = sorted(_counter(r[0]) for r in rows)
    assert counters == list(range(counters[0], counters[-1] + 1)), (
        "telemetry gap across host crash/adoption — counters missing: "
        f"{sorted(set(range(counters[0], counters[-1] + 1)) - set(counters))}"
    )
    _no_duplicate_report_ids(db, meta["dataflow_id"])


def test_recover_adopt_failure_stops_exact_watchdog_then_fresh(meta, wire, db):
    """Row 3: when adoption fails, the coordinator must gracefully stop that
    exact watchdog (verified exit + lease release), then start fresh."""
    _require_mode(meta, "recover-adopt-fail", "old_ownership_after")
    wd_old, wd_new = meta.get("watchdog_before"), meta.get("watchdog_b")

    assert meta.get("old_watchdog_pid_alive_after") is False, (
        "the orphaned watchdog is still alive — stop_exact_watchdog did not verify "
        "its exit before proceeding"
    )
    assert wd_new, (
        "no fresh watchdog after stop-then-fresh — either the graceful stop / lease "
        f"release was unverified or the fresh start failed: {meta.get('old_ownership_after')}"
    )
    assert wd_new != wd_old, "stop-then-fresh must mint a new watchdog identity"

    accepted_fresh = [e for e, s, _t in wire if e["watchdog_id"] == wd_new and s == 202]
    assert accepted_fresh, (
        "fresh watchdog never streamed — if its log shows the devices busy, the "
        "graceful stop did not actually release the hardware (lease freed but COM "
        "ports still held): real finding"
    )

    old_after = meta.get("old_ownership_after") or {}
    assert old_after.get("state") == "stopped", (
        f"old runtime's ownership should be 'stopped', is {old_after.get('state')!r}"
    )
    _no_duplicate_report_ids(db, meta["dataflow_id"])


def test_recover_conflict_blocks_hardware_and_backs_off(meta, wire, db):
    """Row 4: conflicting evidence (token mismatch) must keep the runtime
    RECOVERING with a scheduled backoff — no fresh spawn, hardware untouched —
    and resolve to adoption once the evidence is repaired."""
    _require_mode(meta, "recover-conflict", "conflict_injected_at", "conflict_window_end")
    wd = meta.get("watchdog_before")

    snap = meta.get("recovering_snapshot") or {}
    assert snap.get("state") == "recovering", (
        f"ownership should be RECOVERING under conflicting evidence, is {snap.get('state')!r}"
    )
    rec = _recovery_details(snap)
    assert rec.get("phase") == "retry_wait", f"expected retry_wait, got {rec.get('phase')!r}"
    assert rec.get("next_retry_at"), "no backoff retry scheduled (next_retry_at missing)"
    assert int(rec.get("attempt") or 0) >= 1, "no recovery attempt recorded"

    # Backoff probes actually re-fired during the conflict window.
    late = _recovery_details(meta.get("recovering_snapshot_late"))
    assert int(late.get("attempt") or 0) >= int(rec.get("attempt") or 0), (
        "attempt counter did not advance — the scheduled re-probe never fired"
    )

    # Hardware stayed blocked: no replacement spawned, no foreign watchdog on the wire.
    assert meta.get("host_respawned_during_conflict") is False, (
        "a replacement host was spawned on conflicting evidence — the coordinator "
        "must hold RECOVERING instead"
    )
    start, end = _ts(meta["conflict_injected_at"]), _ts(meta["conflict_window_end"])
    foreign = [
        e for e, _s, ts in wire
        if ts and start < _ts(ts) < end and e["watchdog_id"] != wd
    ]
    assert not foreign, f"another watchdog touched the wire during the conflict: {foreign[:2]}"

    # The original watchdog kept streaming throughout — blocked ≠ interrupted.
    during = [e for e, s, ts in wire if s == 202 and ts and start < _ts(ts) < end]
    assert during, "the live watchdog stopped streaming during the conflict window"

    # Repairing the evidence resolved to ADOPTION of the same watchdog.
    assert meta.get("watchdog_after") == wd, (
        f"after evidence repair the SAME watchdog should be adopted: before={wd!r} "
        f"after={meta.get('watchdog_after')!r}"
    )
    _no_duplicate_report_ids(db, meta["dataflow_id"])


# ── Packet 30: multi-sink matrix evidence (opt-in hardware) ───────────────────


def test_multi_sink_matrix_evidence_recorded_when_present(meta):
    """When a hardware checkpoint records a multi-sink matrix, require the
    packet-30 evidence fields. Pure CSV historical captures skip cleanly so
    ordinary CI stays green without hardware.
    """
    matrix = meta.get("sink_matrix") or meta.get("sinks")
    if not matrix:
        pytest.skip(
            "checkpoint meta has no sink_matrix — re-run checkpoint with a "
            "multi-sink template (CSV+EDF/PVFS and/or Influx/Quest/Plot) for "
            "packet 30 hardware evidence"
        )

    assert isinstance(matrix, list) and matrix, "sink_matrix must be a non-empty list"
    sink_ids = []
    for entry in matrix:
        assert "sink_id" in entry and "sink_type" in entry, entry
        assert entry["sink_id"], "sink_id must be non-empty"
        sink_ids.append(entry["sink_id"])
        # Secrets never land in hardware evidence manifests.
        blob = json.dumps(entry)
        for forbidden in ("api_token", "password", "secret", "Authorization"):
            assert forbidden not in blob

    assert len(sink_ids) == len(set(sink_ids)), "duplicate sink identities in matrix"

    # Optional richer evidence for release notes (packet 31).
    if meta.get("failure_injection"):
        assert meta.get("pass") in (True, False)
        assert meta.get("artifacts") or meta.get("artifact_paths"), (
            "failure_injection runs must record artifacts for packet 31"
        )
