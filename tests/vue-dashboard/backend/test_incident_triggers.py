"""M5 follow-on: widen incident triggers beyond confirmed-unhealthy streams.

Covers the other two of the audit's four incident triggers now wired:
unreachable (poller-driven) and failed-op (operations-driven). Also regression-
tests the dedup-collision hazard both dataflow-scope triggers share: they both
key on device_id=None, so the reason string must keep them from cross-resolving.

Also covers the four watchdog-process/telemetry triggers added once direct
watchdog-process telemetry and respawn tracking existed to observe them:
watchdog crash, crash loop, stale watchdog process, and stale/overflowing
direct telemetry (see app.services.incidents).
"""

from datetime import UTC, datetime, timedelta

from structlog.contextvars import bind_contextvars

from uuid import uuid4

from app.services import device_configs
from app.services import session_templates
from app.services import device_templates

import app.services.sessions as session_service
from app import create_app
from app.control.event_poller import DataflowTarget, EventPoller
from app.database import db, transaction
from app.domain.enums import DeviceType, IncidentStatus
from app.models.backend_event import BackendEvent
from app.repositories.backend_events import BackendEventRepository
from app.repositories.incidents import IncidentRepository
from app.repositories.runtime_ownership import RuntimeOwnershipRepository
from app.repositories.sessions import SessionRepository
from app.services.device_configs import create as create_device_config
from app.services.incidents import (
    CRASH_LOOP_REASON,
    HOST_UNREACHABLE_REASON,
    OUTBOX_OVERFLOW_REASON,
    STALE_PROCESS_REASON,
    STALE_TELEMETRY_REASON,
    WATCHDOG_CRASH_REASON,
)
from app.watchdog.adapters import FakeWatchdogAdapter, WatchdogUnavailableError


def _session_with_dataflow(app, dataflow_id: str) -> int:
    with app.app_context():
        session = SessionRepository().create({"name": "Trigger Test"})
        with transaction():
            session.dataflow_id = dataflow_id
        return session.id


def _valid_flow(hardware_id: str = "001", port: str = "COM4"):
    config = create_device_config(
        device_type=DeviceType.POD8206HR,
        hardware_id=hardware_id,
        port=port,
        parameters={"preamp_gain": 10},
    )
    return {
        "device_config_id": config.id,
        "sink_type": "csv",
        "sink_location": f"C:/data/{hardware_id}.csv",
    }


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakeSupervisor:
    """Dispatch fails until ``fail_times`` calls have been consumed, then succeeds."""

    def __init__(self, *, fail_times: int = 0) -> None:
        self._fail_remaining = fail_times
        self.dispatched: list = []

    def spawn(self, session, *, manifest=None):
        session.runtime_port = 1
        session.runtime_token = "t"
        return 1

    def dispatch(self, session, envelope):
        self.dispatched.append(envelope)
        if self._fail_remaining > 0:
            self._fail_remaining -= 1
            raise WatchdogUnavailableError("Runtime host is unavailable.")

    def stop(self, session, *, envelope=None):
        session.runtime_port = None
        session.runtime_token = None


def _create_device_config(
    *,
    hardware_id="001",
    port="COM3",
):
    """Create a device config suitable for a session/template test."""
    return device_configs.create(
        device_type=DeviceType.POD8206HR,
        hardware_id=hardware_id,
        port=port,
        parameters={"preamp_gain": 10},
    )


def _create_template(*, tmp_path, name="bench-rig"):
    """Create a real device template and register a session template from it."""

    unique_name = f"{name}-{uuid4().hex[:8]}"

    device_template = device_templates.create(
        name,
        {
            "type": "pod8206hr",
            "parameters": {"preamp_gain": 10},
        },
    )

    return session_templates.create(
        f"{unique_name}-session",
        {
            "policy": "recommend",
            "device_flows": [
                {
                    "device_template_path": device_template.file_path,
                    "sinks": [
                        {
                            "sink_type": "csv",
                            "sink_location": "test_output/out.csv",
                        }
                    ],
                }
            ],
        },
    )


# ── failed-op (operations-driven) ─────────────────────────────────────────────


def test_failed_start_opens_incident_and_successful_retry_resolves_it(
    tmp_path,
):
    supervisor = FakeSupervisor(fail_times=1)
    app = create_app("testing")

    with app.app_context():
        db.create_all()

        config = _create_device_config()
        template = _create_template(tmp_path=tmp_path)

        session = session_service.create(
            {
                "name": "failed-op-session",
                "source_template_id": template.template_id,
                "expected_template_hash": template.registered_hash,
                "assignments": [
                    {
                        "flow_index": 0,
                        "device_config_id": config.id,
                        "sink_locations": [
                            {
                                "sink_index": 0,
                                "sink_location": str(
                                    tmp_path / "output.csv"
                                ),
                            }
                        ],
                    }
                ],
            }
        )

        bind_contextvars(request_id="req-failed-start-1")

        try:
            session_service.start_managed(session.id, supervisor)
            raise AssertionError("expected the first start to fail")
        except WatchdogUnavailableError:
            pass

        opened = IncidentRepository().list_for_session(session.id)

        assert len(opened) == 1
        assert opened[0].reason == "operation failed: start"
        assert opened[0].device_id is None
        assert opened[0].status == IncidentStatus.OPEN.value

        bind_contextvars(request_id="req-failed-start-2")

        session_service.start_managed(session.id, supervisor)

        resolved = IncidentRepository().list_for_session(session.id)

        assert len(resolved) == 1
        assert resolved[0].status == IncidentStatus.RESOLVED.value
        assert resolved[0].resolution == "start succeeded"


def test_repeated_failed_recovery_dedups_and_stays_scoped_to_its_device(tmp_path):
    app = create_app("testing")
    supervisor = FakeSupervisor(fail_times=0)

    with app.app_context():
        db.create_all()

        config = _create_device_config()
        template = _create_template(tmp_path=tmp_path)

        session = session_service.create(
            {
                "name": "failed-op-session",
                "source_template_id": template.template_id,
                "expected_template_hash": template.registered_hash,
                "assignments": [
                    {
                        "flow_index": 0,
                        "device_config_id": config.id,
                        "sink_locations": [
                            {
                                "sink_index": 0,
                                "sink_location": str(
                                    tmp_path / "output.csv"
                                ),
                            }
                        ],
                    }
                ],
            }
        )

        bind_contextvars(request_id="req-recover-fail-start")
        session_service.start_managed(session.id, supervisor)

        supervisor._fail_remaining = 2
        for i in range(2):
            bind_contextvars(request_id=f"req-recover-fail-{i}")
            try:
                session_service.recover_managed(
                    session.id, "dev-op002", "reconnect", supervisor
                )
                raise AssertionError("expected recovery dispatch to fail")
            except WatchdogUnavailableError:
                pass

        rows = IncidentRepository().list_for_session(session.id)
        stream_scope = [r for r in rows if r.device_id == "dev-op002"]
        dataflow_scope = [r for r in rows if r.device_id is None]

        assert len(stream_scope) == 1
        assert stream_scope[0].reason == "operation failed: reconnect"
        # the earlier successful "start" must not have left a stray incident
        assert dataflow_scope == []


# ── unreachable (poller-driven) ───────────────────────────────────────────────


def test_unreachable_link_opens_incident_and_reachable_resolves_it(app):
    session_id = _session_with_dataflow(app, "df-unreachable")
    clock = FakeClock(datetime(2026, 7, 7, 12, 0, tzinfo=UTC))
    calls = 0

    def probe_status(port: int) -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            # establishes last_received_at via a real ingested report
            return {
                "dataflow_id": "df-unreachable",
                "phase": "running",
                "reports": [
                    {
                        "dataflow_id": "df-unreachable",
                        "phase": "running",
                        "comms": "current",
                        "devices": [],
                        "sequence": 1,
                    }
                ],
            }
        raise TimeoutError("probe failed")

    poller = EventPoller(
        targets=lambda: [DataflowTarget("df-unreachable", 9101)],
        probe_status=probe_status,
        delayed_after_seconds=5,
        unreachable_after_seconds=10,
        clock=clock,
    )

    with app.app_context():
        first = poller.poll_once()[0]
        clock.now = first.last_received_at
        clock.advance(11)
        second = poller.poll_once()[0]

        after_unreachable = IncidentRepository().list_for_session(session_id)

    assert first.link_status.value == "reachable"
    assert second.link_status.value == "unreachable"
    assert len(after_unreachable) == 1
    assert after_unreachable[0].reason == HOST_UNREACHABLE_REASON
    assert after_unreachable[0].status == IncidentStatus.OPEN.value

    # a later successful probe with a FRESH report resumes reachability — the
    # clock must sit close to that fresh received_at for age_seconds to clear
    # the delayed threshold too, not just the unreachable one.
    def probe_status_recovered(port: int) -> dict:
        return {
            "dataflow_id": "df-unreachable",
            "phase": "running",
            "reports": [
                {
                    "dataflow_id": "df-unreachable",
                    "phase": "running",
                    "comms": "current",
                    "devices": [],
                    "sequence": 2,
                }
            ],
        }

    poller._probe_status = probe_status_recovered
    with app.app_context():
        # first recovered poll ingests the fresh report but the fake clock is
        # still 11s stale relative to it; resync (mirrors the established
        # pattern above) and poll once more for a clean age≈0 reading.
        interim = poller.poll_once()[0]
        clock.now = interim.last_received_at
        fourth = poller.poll_once()[0]
        resolved = IncidentRepository().list_for_session(session_id)

    assert fourth.link_status.value == "reachable"
    assert resolved[0].status == IncidentStatus.RESOLVED.value


def test_repeated_unreachable_polls_dedup_to_one_incident(app):
    session_id = _session_with_dataflow(app, "df-unreachable-dedup")
    clock = FakeClock(datetime(2026, 7, 7, 12, 0, tzinfo=UTC))
    calls = 0

    def probe_status(port: int) -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "dataflow_id": "df-unreachable-dedup",
                "phase": "running",
                "reports": [
                    {
                        "dataflow_id": "df-unreachable-dedup",
                        "phase": "running",
                        "comms": "current",
                        "devices": [],
                        "sequence": 1,
                    }
                ],
            }
        raise TimeoutError("down")

    poller = EventPoller(
        targets=lambda: [DataflowTarget("df-unreachable-dedup", 9102)],
        probe_status=probe_status,
        delayed_after_seconds=5,
        unreachable_after_seconds=10,
        clock=clock,
    )

    with app.app_context():
        first = poller.poll_once()[0]
        clock.now = first.last_received_at
        clock.advance(11)
        poller.poll_once()
        clock.advance(1)
        poller.poll_once()

        rows = IncidentRepository().list_for_session(session_id)

    assert len(rows) == 1
    

# ── watchdog process crash / crash loop (poller-driven, live /status) ────────


def test_watchdog_crash_opens_incident_and_recovery_resolves_it(app):
    session_id = _session_with_dataflow(app, "df-wd-crash")
    calls = 0

    def probe_status(port: int) -> dict:
        nonlocal calls
        calls += 1
        state = "crashed" if calls == 1 else "running"
        return {
            "dataflow_id": "df-wd-crash",
            "phase": "running",
            "watchdog_id": "wd-1",
            "watchdog_state": state,
            "reports": [],
        }

    poller = EventPoller(
        targets=lambda: [DataflowTarget("df-wd-crash", 9201)],
        probe_status=probe_status,
    )

    with app.app_context():
        poller.poll_once()
        opened = IncidentRepository().list_for_session(session_id)
        assert len(opened) == 1
        assert opened[0].reason == WATCHDOG_CRASH_REASON
        assert opened[0].status == IncidentStatus.OPEN.value

        poller.poll_once()
        resolved = IncidentRepository().list_for_session(session_id)
        assert resolved[0].status == IncidentStatus.RESOLVED.value


def test_repeated_crashed_polls_dedup_to_one_incident(app):
    _session_with_dataflow(app, "df-wd-crash-dedup")
    poller = EventPoller(
        targets=lambda: [DataflowTarget("df-wd-crash-dedup", 9202)],
        probe_status=lambda port: {
            "dataflow_id": "df-wd-crash-dedup",
            "phase": "running",
            "watchdog_id": "wd-1",
            "watchdog_state": "crashed",
            "reports": [],
        },
    )

    with app.app_context():
        poller.poll_once()
        poller.poll_once()
        rows = IncidentRepository().list_for_session(
            SessionRepository().get_by_dataflow_id("df-wd-crash-dedup").id
        )

    assert len(rows) == 1


def test_crash_loop_opens_incident_when_respawn_exhausted_and_fresh_budget_resolves_it(app):
    session_id = _session_with_dataflow(app, "df-crash-loop")
    calls = 0

    def probe_status(port: int) -> dict:
        nonlocal calls
        calls += 1
        exhausted = calls == 1
        return {
            "dataflow_id": "df-crash-loop",
            "phase": "running",
            "watchdog_id": "wd-1",
            "watchdog_state": "running",
            "watchdog_respawn_exhausted": exhausted,
            "reports": [],
        }

    poller = EventPoller(
        targets=lambda: [DataflowTarget("df-crash-loop", 9203)],
        probe_status=probe_status,
    )

    with app.app_context():
        poller.poll_once()
        opened = IncidentRepository().list_for_session(session_id)
        assert len(opened) == 1
        assert opened[0].reason == CRASH_LOOP_REASON
        assert opened[0].status == IncidentStatus.OPEN.value

        poller.poll_once()
        resolved = IncidentRepository().list_for_session(session_id)
        assert resolved[0].status == IncidentStatus.RESOLVED.value


def test_watchdog_signals_are_skipped_when_this_ticks_probe_fails(app):
    """Crash/crash-loop come from THIS tick's live /status payload — a failed
    probe has no fresh evidence, so neither trigger fires (the last-observed
    incident state, if any, simply persists)."""
    _session_with_dataflow(app, "df-wd-probe-fails")
    poller = EventPoller(
        targets=lambda: [DataflowTarget("df-wd-probe-fails", 9204)],
        probe_status=lambda port: (_ for _ in ()).throw(TimeoutError("down")),
        unreachable_after_seconds=999999,  # keep link-status noise out of this assertion
    )

    with app.app_context():
        poller.poll_once()
        rows = IncidentRepository().list_for_session(
            SessionRepository().get_by_dataflow_id("df-wd-probe-fails").id
        )

    assert rows == []


# ── stale watchdog process (poller-driven, durable RuntimeOwnership state) ───


def test_stale_watchdog_heartbeat_opens_incident_and_fresh_heartbeat_resolves_it(app):
    session_id = _session_with_dataflow(app, "df-stale-process")
    clock = FakeClock(datetime(2026, 7, 7, 12, 0, tzinfo=UTC))

    with app.app_context():
        RuntimeOwnershipRepository().create_starting(
            runtime_id="rt-stale-process",
            session_id=session_id,
            dataflow_id="df-stale-process",
            manifest_hash="hash-stale-process",
            token=None,
        )
        ownership = RuntimeOwnershipRepository().set_watchdog(
            "rt-stale-process", watchdog_id="wd-1"
        )
        # Sync the fake clock to the (real-time-stamped) heartbeat, then push
        # it well past the staleness threshold.
        clock.now = ownership.watchdog_last_seen_at
        clock.advance(11)

        poller = EventPoller(
            targets=lambda: [DataflowTarget("df-stale-process", 9205)],
            probe_status=lambda port: {"dataflow_id": "df-stale-process", "phase": "running", "reports": []},
            watchdog_stale_after_seconds=10,
            clock=clock,
        )
        poller.poll_once()

        opened = IncidentRepository().list_for_session(session_id)
        assert len(opened) == 1
        assert opened[0].reason == STALE_PROCESS_REASON
        assert opened[0].status == IncidentStatus.OPEN.value

        # A fresh heartbeat (poll-reconciled elsewhere) resolves it.
        RuntimeOwnershipRepository().update_watchdog_seen("rt-stale-process", watchdog_id="wd-1")
        fresh = RuntimeOwnershipRepository().get("rt-stale-process")
        clock.now = fresh.watchdog_last_seen_at
        poller.poll_once()

        resolved = IncidentRepository().list_for_session(session_id)
        assert resolved[0].status == IncidentStatus.RESOLVED.value


# ── stale / overflowing direct watchdog telemetry (poller-driven, durable) ───


def test_direct_telemetry_staleness_escalates_to_overflow_and_recovery_resolves_both(app):
    session_id = _session_with_dataflow(app, "df-telemetry-fresh")
    clock = FakeClock(datetime(2026, 7, 7, 12, 0, tzinfo=UTC))

    with app.app_context():
        event_id = BackendEventRepository().append(
            event_type="runtime.report",
            session_id=session_id,
            dataflow_id="df-telemetry-fresh",
            payload={"devices": []},
            runtime_id="rt-1",
            watchdog_id="wd-1",
            report_id="wd-1:0",
        )
        received_at = db.session.get(BackendEvent, event_id).received_at

        poller = EventPoller(
            targets=lambda: [DataflowTarget("df-telemetry-fresh", 9206)],
            probe_status=lambda port: {
                "dataflow_id": "df-telemetry-fresh",
                "phase": "running",
                "reports": [],
            },
            telemetry_stale_after_seconds=10,
            telemetry_overflow_after_seconds=30,
            clock=clock,
        )

        # current: no telemetry incident yet.
        clock.now = received_at
        poller.poll_once()
        assert IncidentRepository().list_for_session(session_id) == []

        # stale: past the soft threshold, short of the hard one.
        clock.advance(11)
        poller.poll_once()
        stale_rows = IncidentRepository().list_for_session(session_id)
        assert len(stale_rows) == 1
        assert stale_rows[0].reason == STALE_TELEMETRY_REASON
        assert stale_rows[0].status == IncidentStatus.OPEN.value

        # overflow: escalates past the hard threshold — stale resolves, overflow opens.
        clock.advance(20)
        poller.poll_once()
        rows_by_reason = {
            row.reason: row for row in IncidentRepository().list_for_session(session_id)
        }
        assert rows_by_reason[STALE_TELEMETRY_REASON].status == IncidentStatus.RESOLVED.value
        assert rows_by_reason[OUTBOX_OVERFLOW_REASON].status == IncidentStatus.OPEN.value

        # recovery: a fresh direct-telemetry report resolves the overflow too.
        BackendEventRepository().append(
            event_type="runtime.report",
            session_id=session_id,
            dataflow_id="df-telemetry-fresh",
            payload={"devices": []},
            runtime_id="rt-1",
            watchdog_id="wd-1",
            report_id="wd-1:1",
        )
        fresh_latest = BackendEventRepository().latest_direct_telemetry_for_session(session_id)
        clock.now = fresh_latest.received_at
        poller.poll_once()

        rows_by_reason = {
            row.reason: row for row in IncidentRepository().list_for_session(session_id)
        }
        assert rows_by_reason[OUTBOX_OVERFLOW_REASON].status == IncidentStatus.RESOLVED.value
