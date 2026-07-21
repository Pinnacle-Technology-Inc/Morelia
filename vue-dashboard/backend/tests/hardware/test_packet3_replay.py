"""Packet-3/5 acceptance criteria, replayed against REAL captured traffic.

The inputs here are not authored — they are loaded from a capture file produced
by ``checkpoint.py`` running a real watchdog. That is the whole point: an AI (or
you, or me) cannot make these pass by writing a convenient fake, because the
stimulus is recorded reality.

Each test maps to one acceptance criterion:

    AC1 — the direct-ingest envelope carries every required identity field.
    AC2 — a stale (superseded) watchdog_id is rejected by the receiver's fencing.
    AC3 — duplicate report_id returns the existing event id, no second row.

Capture modes (checkpoint.py):
    (default, old path)  -> old {protocol_version, report} envelope. AC1 SKIPs
                            with the finding "packet-5 sender not in the live
                            path yet".
    --packet5            -> packet-5 flat envelope with identity fields. AC1
                            PASSes; AC3 replays dedup through the real receiver.
    --packet5 --faults   -> also records a respawn: watchdog B supersedes A and a
                            late A report is fenced (409). AC2 asserts that.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.database import transaction
from app.repositories.backend_events import BackendEventRepository
from app.repositories.sessions import SessionRepository
from tests.hardware.capture import iter_envelopes, load_captures

CAPTURE_FILE = Path(__file__).parent / "fixtures" / "latest_capture.jsonl"

# Fields the direct-ingest (packet-5) envelope must carry.
REQUIRED_ENVELOPE_FIELDS = frozenset(
    {
        "report_id",
        "session_id",
        "dataflow_id",
        "runtime_id",
        "watchdog_id",
        "manifest_hash",
        "event_type",
    }
)


@pytest.fixture
def captures():
    caps = load_captures(CAPTURE_FILE)
    if not caps:
        pytest.skip(
            f"no capture at {CAPTURE_FILE.name}: run "
            "`python -m tests.hardware.checkpoint --template <t> --packet5` first"
        )
    return caps


def _reports(captures) -> list[dict]:
    """The report/identity dict from every parseable captured envelope.

    Handles both wire formats: OLD runtime_host push ``{"protocol_version", "report"}``
    (fields under "report") and NEW packet-5 flat telemetry (identity fields at
    the top level).
    """
    return [env["report"] if "report" in env else env for env in iter_envelopes(captures)]


def _packet5_envelopes(captures) -> list[tuple[dict, int | None]]:
    """(envelope, http_status) for each captured PACKET-5 flat envelope.

    The status is what the LIVE receiver returned at capture time — 202 accepted,
    409 fenced — which is the evidence AC2 asserts on.
    """
    out: list[tuple[dict, int | None]] = []
    for cap in captures:
        try:
            env = json.loads(cap.get("raw", ""))
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(env, dict) and "report_id" in env and "phase" not in env:
            out.append((env, cap.get("status")))
    return out


def _register_identity(envelope: dict, *, active_watchdog_id: str | None = None) -> None:
    """Recreate a captured envelope's identity so the receiver's fencing passes.

    The capture references a session/runtime/watchdog that don't exist in this
    fresh test DB, so reconstruct them: a session with the envelope's exact id,
    a runtime ownership row, and the active watchdog set (defaults to the
    envelope's own watchdog_id; override to make it stale).
    """
    from app.database import db
    from app.models.session import Session
    from app.repositories.runtime_ownership import RuntimeOwnershipRepository

    sid = int(envelope["session_id"])
    if db.session.get(Session, sid) is None:
        with transaction():
            db.session.add(Session(id=sid, name=f"replay-{sid}", dataflow_id=envelope["dataflow_id"]))

    repo = RuntimeOwnershipRepository()
    if repo.get(envelope["runtime_id"]) is None:
        repo.create_starting(
            runtime_id=envelope["runtime_id"],
            session_id=sid,
            dataflow_id=envelope["dataflow_id"],
            manifest_hash=envelope["manifest_hash"],
            token=None,
        )
    repo.set_watchdog(
        envelope["runtime_id"], watchdog_id=active_watchdog_id or envelope["watchdog_id"]
    )


# ── AC1: the real envelope carries every required identity field ──────────────

def test_ac1_real_envelope_carries_required_fields(captures):
    """The REAL captured traffic must carry every required identity field.

    If it does not, the packet-5 sender is not in the live path (the default
    checkpoint still records the old runtime_host envelope) — surfaced here
    instead of by a false green in the fast suite.
    """
    reports = _reports(captures)
    assert reports, "capture had no parseable reports"

    missing_by_report = [set(REQUIRED_ENVELOPE_FIELDS) - set(r) for r in reports]
    absent_everywhere = set(missing_by_report[0])
    for missing in missing_by_report[1:]:
        absent_everywhere &= missing
    if absent_everywhere:
        pytest.skip(
            "packet-5 envelope is not in this capture — the recorded sender never "
            f"emits {sorted(absent_everywhere)}. Run `checkpoint.py --packet5` to "
            "record the watchdog-process telemetry envelope."
        )

    for report, missing in zip(reports, missing_by_report):
        assert not missing, f"captured report missing {sorted(missing)}: {report}"


# ── AC3: duplicate report_id dedupes to one row / same id ─────────────────────

def test_ac3_duplicate_report_id_returns_same_id(app, captures):
    """Re-POST a captured packet-5 envelope through the REAL receiver twice:
    same event id, exactly one row (dedup on report_id)."""
    envelopes = [env for env, _status in _packet5_envelopes(captures)]
    if not envelopes:
        pytest.skip("no packet-5 flat envelope captured — run `checkpoint.py --packet5`")

    env = envelopes[0]
    with app.app_context():
        _register_identity(env)

    client = app.test_client()
    first = client.post("/api/v1/internal/events", json=env)
    second = client.post("/api/v1/internal/events", json=env)

    assert first.status_code == 202, (first.status_code, first.get_json())
    assert second.status_code == 202, (second.status_code, second.get_json())
    assert first.get_json()["event_id"] == second.get_json()["event_id"], (
        "duplicate report_id returned a different event id"
    )

    with app.app_context():
        rows = BackendEventRepository().since(int(env["session_id"]), after_id=0, limit=1000)
    matching = [r for r in rows if getattr(r, "report_id", None) == env["report_id"]]
    assert len(matching) == 1, f"duplicate report_id created {len(matching)} rows, expected 1"


# ── AC2: a superseded watchdog_id is fenced by the live receiver ──────────────

def test_ac2_stale_watchdog_id_rejected(captures):
    """The live receiver's fencing is recorded in the capture's HTTP statuses.

    A ``--packet5 --faults`` run streams watchdog A (accepted, 202), supersedes
    it with B, then sends a late report from the now-stale A — which the real
    receiver fences (409). The proof is one watchdog_id that was ACCEPTED while
    active and then FENCED after supersession. No re-derivation: both verdicts
    are the real control plane's own, recorded at capture time.
    """
    p5 = _packet5_envelopes(captures)
    if not p5:
        pytest.skip("no packet-5 flat envelope captured — run `checkpoint.py --packet5`")

    fenced = {env["watchdog_id"] for env, status in p5 if status == 409}
    accepted = {env["watchdog_id"] for env, status in p5 if status == 202}

    if not fenced:
        pytest.skip(
            "no fenced (409) report captured — run `checkpoint.py --packet5 --faults` "
            "to record a respawn that supersedes a watchdog"
        )

    # The same watchdog_id was accepted while active, then fenced once superseded.
    accepted_then_fenced = accepted & fenced
    assert accepted_then_fenced, (
        "expected a watchdog_id accepted (202) while active and then fenced (409) "
        f"after being superseded; accepted={accepted}, fenced={fenced}"
    )
