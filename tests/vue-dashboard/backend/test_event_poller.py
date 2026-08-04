"""Packet 7.4: poll backstop plus link liveness gating."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.control.event_poller import DataflowTarget, EventPoller
from app.database import transaction
from app.domain.enums import CommsStatus, LinkStatus
from app.repositories.backend_events import BackendEventRepository
from app.repositories.sessions import SessionRepository
from app.runtime_child.driver import RuntimePhase, RuntimeReport


def _session_with_dataflow(app, dataflow_id: str) -> int:
    with app.app_context():
        session = SessionRepository().create({"name": "Poll Test"})
        with transaction():
            session.dataflow_id = dataflow_id
        return session.id


def _report(
    dataflow_id: str,
    sequence: int,
    *,
    comms: CommsStatus = CommsStatus.CURRENT,
) -> dict:
    return RuntimeReport(
        dataflow_id=dataflow_id,
        phase=RuntimePhase.RUNNING,
        comms=comms,
        devices=(),
        sequence=sequence,
    ).to_dict()


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def test_poll_recovers_sequence_dropped_by_push_path(app):
    session_id = _session_with_dataflow(app, "df-poll-recover")
    probe_payload = {
        "dataflow_id": "df-poll-recover",
        "phase": "running",
        "reports": [_report("df-poll-recover", sequence=7)],
    }
    poller = EventPoller(
        targets=lambda: [DataflowTarget("df-poll-recover", 8201)],
        probe_status=lambda port: probe_payload,
    )

    with app.app_context():
        snapshot = poller.poll_once()[0]
        rows = BackendEventRepository().since(session_id, after_id=0, limit=10)

    assert snapshot.link_status is LinkStatus.REACHABLE
    assert [row.sequence for row in rows] == [7]


def test_poll_and_push_delivery_of_same_sequence_yields_one_row(app):
    session_id = _session_with_dataflow(app, "df-poll-dedup")
    pushed_id = None
    with app.app_context():
        from app.services.event_ingest import ingest_report

        pushed_id = ingest_report(_report("df-poll-dedup", sequence=3))

    poller = EventPoller(
        targets=lambda: [DataflowTarget("df-poll-dedup", 8202)],
        probe_status=lambda port: {
            "dataflow_id": "df-poll-dedup",
            "phase": "running",
            "reports": [_report("df-poll-dedup", sequence=3)],
        },
    )

    with app.app_context():
        poller.poll_once()
        rows = BackendEventRepository().since(session_id, after_id=0, limit=10)

    assert len(rows) == 1
    assert rows[0].id == pushed_id
    assert rows[0].sequence == 3


def test_stale_then_dead_moves_delayed_then_unreachable_after_failed_probe(app):
    _session_with_dataflow(app, "df-poll-liveness")
    clock = FakeClock(datetime(2026, 6, 29, 12, 0, tzinfo=UTC))
    probe_calls = 0

    def probe_status(port: int) -> dict:
        nonlocal probe_calls
        probe_calls += 1
        if probe_calls == 1:
            return {
                "dataflow_id": "df-poll-liveness",
                "phase": "running",
                "reports": [_report("df-poll-liveness", sequence=1)],
            }
        if probe_calls == 2:
            return {
                "dataflow_id": "df-poll-liveness",
                "phase": "running",
                "reports": [_report("df-poll-liveness", sequence=1)],
            }
        raise TimeoutError("status probe failed")

    poller = EventPoller(
        targets=lambda: [DataflowTarget("df-poll-liveness", 8203)],
        probe_status=probe_status,
        delayed_after_seconds=5,
        unreachable_after_seconds=10,
        clock=clock,
    )

    with app.app_context():
        first = poller.poll_once()[0]
        assert first.last_received_at is not None
        clock.now = first.last_received_at
        clock.advance(6)
        delayed = poller.poll_once()[0]
        clock.advance(5)
        unreachable = poller.poll_once()[0]

    assert first.link_status is LinkStatus.REACHABLE
    assert delayed.link_status is LinkStatus.DELAYED
    assert unreachable.link_status is LinkStatus.UNREACHABLE
    assert probe_calls == 3


def test_report_comms_unreachable_is_only_a_delayed_hint(app):
    _session_with_dataflow(app, "df-poll-comms")
    poller = EventPoller(
        targets=lambda: [DataflowTarget("df-poll-comms", 8204)],
        probe_status=lambda port: {
            "dataflow_id": "df-poll-comms",
            "phase": "running",
            "reports": [
                _report(
                    "df-poll-comms",
                    sequence=1,
                    comms=CommsStatus.UNREACHABLE,
                )
            ],
        },
    )

    with app.app_context():
        snapshot = poller.poll_once()[0]

    assert snapshot.link_status is LinkStatus.DELAYED
