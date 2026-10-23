"""M5 wiring: incidents (5b) and recovery gaps (5c) born in the ingest path.

Packet 21 extends this to the per-sink axis: per-sink incidents, monotonic
delivery-loss/current-state on ``output_files``, and per-sink recovery
boundaries — all keyed by durable sink identity and kept strictly separate from
source/stream health.
"""

import time
from queue import Queue
from types import SimpleNamespace

import pytest
from structlog.contextvars import bind_contextvars

import app.services.sessions as session_service
from Morelia.Watchdog.watchdog import StreamWatcher
from app.database import db, transaction
from app.domain.enums import DeviceType, IncidentStatus, OperationScope, PolicyMode, SinkType
from app.models.operation import Operation
from app.models.output_file import OutputFile
from app.models.recovery_gap import RecoveryGap
from app.repositories.incidents import IncidentRepository
from app.repositories.recovery_gaps import RecoveryGapRepository
from app.repositories.sessions import SessionRepository
from app.runtime_child import morelia
from app.runtime_child.driver import RuntimePhase
from app.runtime_host.manifest import DeviceFlow, Manifest
from app.services.device_configs import create as create_device_config
from app.services.event_ingest import ingest_report
from app.services.gaps import evaluate_report


def _report(
    dataflow_id: str, *, sequence: int, status: str, recovery_id: str | None = None
) -> dict:
    raw = {
        "dataflow_id": dataflow_id,
        "phase": "running",
        "comms": "current",
        "devices": [{"device_id": "dev-op001", "stream_status": status}],
        "sequence": sequence,
    }
    if recovery_id is not None:
        raw["recovery_id"] = recovery_id
    return raw


def _session_with_dataflow(app, dataflow_id: str) -> int:
    with app.app_context():
        session = SessionRepository().create({"name": "M5 wiring"})
        with transaction():
            session.dataflow_id = dataflow_id
        return session.id


# ── 5b: incident lifecycle from the report stream ────────────────────────────


def test_unhealthy_report_opens_incident_and_dedups(app):
    session_id = _session_with_dataflow(app, "df-inc")
    incidents = IncidentRepository()

    with app.app_context():
        ingest_report(_report("df-inc", sequence=1, status="unhealthy"))
        ingest_report(_report("df-inc", sequence=2, status="unhealthy"))

        rows = incidents.list_for_session(session_id)
        assert len(rows) == 1
        assert rows[0].status == IncidentStatus.OPEN.value
        assert rows[0].device_id == "dev-op001"
        assert rows[0].reason == "stream unhealthy"


def test_suspect_report_opens_no_incident(app):
    session_id = _session_with_dataflow(app, "df-suspect")

    with app.app_context():
        ingest_report(_report("df-suspect", sequence=1, status="suspect"))
        assert IncidentRepository().list_for_session(session_id) == []


def test_recovered_stream_resolves_then_reopens_a_fresh_incident(app):
    session_id = _session_with_dataflow(app, "df-cycle")
    incidents = IncidentRepository()

    with app.app_context():
        ingest_report(_report("df-cycle", sequence=1, status="unhealthy"))
        ingest_report(_report("df-cycle", sequence=2, status="healthy"))

        resolved = incidents.list_for_session(session_id)
        assert len(resolved) == 1
        assert resolved[0].status == IncidentStatus.RESOLVED.value

        ingest_report(_report("df-cycle", sequence=3, status="unhealthy"))
        rows = incidents.list_for_session(session_id)
        assert len(rows) == 2
        assert rows[0].status == IncidentStatus.OPEN.value  # newest first


def test_incident_list_show_and_ack_routes(app):
    session_id = _session_with_dataflow(app, "df-routes")
    with app.app_context():
        ingest_report(_report("df-routes", sequence=1, status="unhealthy"))
        incident_id = IncidentRepository().list_for_session(session_id)[0].incident_id

    client = app.test_client()

    listed = client.get(f"/api/v1/incidents?session={session_id}")
    assert listed.status_code == 200
    body = listed.get_json()
    assert [i["incident_id"] for i in body["items"]] == [incident_id]

    shown = client.get(f"/api/v1/incidents/{incident_id}")
    assert shown.status_code == 200
    assert shown.get_json()["status"] == "open"

    acked = client.post(
        f"/api/v1/incidents/{incident_id}/ack",
        json={"acknowledged_by": "op@example.com", "note": "checking cable"},
    )
    assert acked.status_code == 200
    body = acked.get_json()
    assert body["status"] == "acknowledged"
    assert body["acknowledged_by"] == "op@example.com"


def test_incident_show_missing_returns_404(app):
    response = app.test_client().get("/api/v1/incidents/nope")
    assert response.status_code == 404
    assert response.get_json()["code"] == "incident_not_found"


# ── 5c: a recovery episode records exactly one gap, linked to its incident ────


def _valid_flow():
    config = create_device_config(
        device_type=DeviceType.POD8206HR,
        hardware_id="001",
        port="COM3",
        parameters={"preamp_gain": 10},
    )
    return {
        "device_config_id": config.id,
        "sink_type": "csv",
        "sink_location": "C:/data/op.csv",
    }


class _FakeSupervisor:
    def spawn(self, session, *, manifest=None):
        session.runtime_port = 43210
        session.runtime_token = "tok"
        return session.runtime_port

    def dispatch(self, session, envelope):
        pass

    def stop(self, session, *, envelope=None):
        session.runtime_port = None
        session.runtime_token = None


# ── Packet 21: per-sink axis ──────────────────────────────────────────────────


def _sink(
    sink_id: str,
    *,
    source_id: str = "dev-op001",
    sink_class: str = "csv",
    health: str = "failed",
    delivery: str = "failed",
    sequence: int = 1,
    state_timestamp_ns: int = 1,
    **extra,
) -> dict:
    payload = {
        "sink_id": sink_id,
        "source_id": source_id,
        "sink_class": sink_class,
        "health": health,
        "delivery": delivery,
        "sequence": sequence,
        "state_timestamp_ns": state_timestamp_ns,
    }
    payload.update(extra)
    return payload


def _report_with_sinks(
    dataflow_id: str,
    *,
    sequence: int,
    sinks: list[dict],
    device_status: str = "healthy",
    device_id: str = "dev-op001",
    recovery_id: str | None = None,
) -> dict:
    raw = {
        "dataflow_id": dataflow_id,
        "phase": "running",
        "comms": "current",
        "devices": [{"device_id": device_id, "stream_status": device_status}],
        "sequence": sequence,
        "sinks": sinks,
    }
    if recovery_id is not None:
        raw["recovery_id"] = recovery_id
    return raw


def test_sink_failure_opens_sink_addressed_incident_and_dedups(app):
    session_id = _session_with_dataflow(app, "df-sink")
    incidents = IncidentRepository()

    with app.app_context():
        ingest_report(_report_with_sinks("df-sink", sequence=1, sinks=[_sink("sink-a")]))
        ingest_report(_report_with_sinks("df-sink", sequence=2, sinks=[_sink("sink-a")]))

        rows = incidents.list_for_session(session_id)
        assert len(rows) == 1
        assert rows[0].reason == "sink failed"
        assert rows[0].sink_id == "sink-a"
        assert rows[0].device_id == "dev-op001"  # owning source
        assert rows[0].status == IncidentStatus.OPEN.value
        # the per-sink diagnostics are the redacted wire fields, no raw samples
        assert rows[0].details["health"] == "failed"
        assert rows[0].details["sink_sequence"] == 1


def test_sink_payload_is_persisted_on_the_backend_event(app):
    _session_with_dataflow(app, "df-payload-sinks")
    from app.repositories.backend_events import BackendEventRepository

    with app.app_context():
        event_id = ingest_report(
            _report_with_sinks(
                "df-payload-sinks", sequence=1, sinks=[_sink("sink-a", health="degraded")]
            )
        )
        session_id = SessionRepository().get_by_dataflow_id("df-payload-sinks").id
        row = next(
            r
            for r in BackendEventRepository().since(session_id, after_id=0, limit=10)
            if r.id == event_id
        )
    assert row.payload["sinks"][0]["sink_id"] == "sink-a"
    assert row.payload["sinks"][0]["health"] == "degraded"


def test_sink_only_failure_leaves_source_stream_health_untouched(app):
    """AC3: a sink-only failure opens no source-stream incident."""
    session_id = _session_with_dataflow(app, "df-axis")
    incidents = IncidentRepository()

    with app.app_context():
        ingest_report(
            _report_with_sinks(
                "df-axis", sequence=1, sinks=[_sink("sink-a")], device_status="healthy"
            )
        )
        rows = incidents.list_for_session(session_id)
        assert [r.reason for r in rows] == ["sink failed"]
        # the source stream is HEALTHY: no stream-unhealthy incident exists
        assert (
            incidents.find_open_for_device(
                session_id, "df-axis", "dev-op001", reason="stream unhealthy"
            )
            is None
        )


def test_sink_health_transitions_keep_at_most_one_open_incident(app):
    session_id = _session_with_dataflow(app, "df-trans")
    incidents = IncidentRepository()

    with app.app_context():
        ingest_report(
            _report_with_sinks(
                "df-trans", sequence=1, sinks=[_sink("s", health="degraded", delivery="degraded")]
            )
        )
        opened = incidents.list_for_session(session_id, status=IncidentStatus.OPEN)
        assert [r.reason for r in opened] == ["sink degraded"]

        ingest_report(
            _report_with_sinks(
                "df-trans", sequence=2, sinks=[_sink("s", health="failed", delivery="failed")]
            )
        )
        opened = incidents.list_for_session(session_id, status=IncidentStatus.OPEN)
        assert [r.reason for r in opened] == ["sink failed"]  # degraded escalated, not doubled
        assert len(incidents.list_for_session(session_id)) == 2

        ingest_report(
            _report_with_sinks(
                "df-trans", sequence=3, sinks=[_sink("s", health="healthy", delivery="delivered")]
            )
        )
        assert incidents.list_for_session(session_id, status=IncidentStatus.OPEN) == []


def test_sink_loss_counters_are_monotonic_and_delivery_state_tracks_latest(app):
    """AC1: replayed/out-of-order reports never lower a durable loss counter."""
    session_id = _session_with_dataflow(app, "df-loss")

    with app.app_context():
        row = OutputFile(
            output_id="out-1",
            logical_sink_id="log-1",
            dataflow_id="df-loss",
            sink_id="sink-x",
            device_id="dev-op001",
            session_id=session_id,
            sink_type="csv",
            path="C:/data/loss.csv",
            delivery_state="pending",
            byte_loss=0,
            sample_loss=0,
        )
        with transaction():
            db.session.add(row)

        ingest_report(
            _report_with_sinks(
                "df-loss",
                sequence=1,
                sinks=[
                    _sink(
                        "sink-x",
                        health="degraded",
                        delivery="degraded",
                        sample_loss=5,
                        byte_loss=50,
                    )
                ],
            )
        )
        assert row.delivery_state == "degraded"
        assert row.sample_loss == 5
        assert row.byte_loss == 50

        # a later report carrying LOWER cumulative loss (replay/out-of-order)
        ingest_report(
            _report_with_sinks(
                "df-loss",
                sequence=2,
                sinks=[
                    _sink(
                        "sink-x",
                        health="degraded",
                        delivery="delivering",
                        sample_loss=2,
                        byte_loss=20,
                    )
                ],
            )
        )
        assert row.sample_loss == 5  # never regressed
        assert row.byte_loss == 50
        assert row.delivery_state == "delivering"  # current state still advances

        # higher totals advance the monotonic counters
        ingest_report(
            _report_with_sinks(
                "df-loss",
                sequence=3,
                sinks=[
                    _sink(
                        "sink-x",
                        health="failed",
                        delivery="failed",
                        sample_loss=8,
                        byte_loss=80,
                    )
                ],
            )
        )
        assert row.sample_loss == 8
        assert row.byte_loss == 80


def _insert_recovery_operation(
    session_id: int, dataflow_id: str, *, recovery_id: str, target_device_id: str
) -> Operation:
    op = Operation(
        operation_id=f"op-{recovery_id}",
        request_key=f"rk-{recovery_id}",
        session_id=session_id,
        dataflow_id=dataflow_id,
        scope=OperationScope.STREAM,
        target_device_id=target_device_id,
        command="reconnect",
        command_id=f"cmd-{recovery_id}",
        recovery_id=recovery_id,
    )
    with transaction():
        db.session.add(op)
    return op


def _insert_output_file(session_id: int, dataflow_id: str, *, sink_id: str, output_id: str) -> None:
    with transaction():
        db.session.add(
            OutputFile(
                output_id=output_id,
                logical_sink_id=f"log-{output_id}",
                dataflow_id=dataflow_id,
                sink_id=sink_id,
                device_id="dev-op001",
                session_id=session_id,
                sink_type="csv",
                path=f"C:/data/{output_id}.csv",
            )
        )


def test_recovery_records_one_boundary_per_sink_linked_to_its_sink_incident(app):
    """AC2: each recovering sink gets its OWN sink-addressed boundary, deduped."""
    session_id = _session_with_dataflow(app, "df-multi")
    incidents = IncidentRepository()
    gaps_repo = RecoveryGapRepository()

    with app.app_context():
        op = _insert_recovery_operation(
            session_id, "df-multi", recovery_id="rec-multi", target_device_id="dev-op001"
        )
        _insert_output_file(session_id, "df-multi", sink_id="sink-a", output_id="out-a")
        _insert_output_file(session_id, "df-multi", sink_id="sink-b", output_id="out-b")

        # both sinks fail (sink incidents open), source stream also unhealthy
        ingest_report(
            _report_with_sinks(
                "df-multi",
                sequence=1,
                device_status="unhealthy",
                sinks=[_sink("sink-a"), _sink("sink-b")],
            )
        )
        assert len(incidents.list_for_session(session_id, status=IncidentStatus.OPEN)) == 3

        # the recovery episode heals: stream + both sinks healthy under recovery_id
        healed = _report_with_sinks(
            "df-multi",
            sequence=2,
            device_status="healthy",
            recovery_id="rec-multi",
            sinks=[
                _sink("sink-a", health="healthy", delivery="delivered"),
                _sink("sink-b", health="healthy", delivery="delivered"),
            ],
        )
        ingest_report(healed)
        # a repeated post-recovery report must not write more boundaries
        ingest_report(healed)

        sink_gaps = [g for g in gaps_repo.list_for_session(session_id) if g.sink_id is not None]
        assert {g.sink_id for g in sink_gaps} == {"sink-a", "sink-b"}
        assert len(sink_gaps) == 2
        for gap in sink_gaps:
            assert gap.recovery_id == "rec-multi"
            assert gap.operation_id == op.operation_id
            assert gap.boundary_kind == "segmented"
            assert gap.device_id == "dev-op001"
            assert gap.output_id in {"out-a", "out-b"}
            # each sink boundary links to that sink's own incident, still open
            # when the boundary is recorded (gaps run before incident resolution)
            assert gap.incident_id is not None
            linked = incidents.get(gap.incident_id)
            assert linked.sink_id == gap.sink_id

        # the source stream also produced its own (sink-less) recovery gap
        source_gaps = [g for g in gaps_repo.list_for_session(session_id) if g.sink_id is None]
        assert len(source_gaps) == 1


GAP_START = 1792006603.0
GAP_DEVICE = "AB0MZ1AVA"


def test_watchdog_preserves_sample_epoch_for_gap_completion():
    watcher = StreamWatcher.__new__(StreamWatcher)
    watcher.stream_index = 1
    watcher._max_heartbeat_age_sec = 10.0
    watcher._monitor = SimpleNamespace(get_stream_heartbeat=lambda *_: {
        "state": "fresh", "last_data_at": GAP_START + 23,
        "age_sec": 0, "packet_count": 1,
    })
    heartbeat = watcher._get_heartbeat()
    assert heartbeat["last_data_at_epoch"] == GAP_START + 23
    assert heartbeat["status"] == "fresh"
    assert heartbeat["packet_count"] == 1


@pytest.fixture
def gap_scenario(app, monkeypatch, tmp_path):
    module = morelia
    clock = [GAP_START]
    monkeypatch.setattr(
        module, "time", SimpleNamespace(
            time=lambda: clock[0], time_ns=lambda: int(clock[0] * 1_000_000_000),
            monotonic=time.monotonic,
        ),
    )
    with app.app_context():
        session = SessionRepository().create({"name": "Session 23 gap oracle"})
        manifest = Manifest(
            schema_version="3", dataflow_id="gap-oracle", session_id=session.id,
            policy=PolicyMode.AUTOMATE,
            device_flows=(DeviceFlow(
                device_id=GAP_DEVICE, name="4", hardware_id=GAP_DEVICE, port="COM3",
                parameters={}, sink_type=SinkType.PVFS,
                sink_location=str(tmp_path / "recording.pvfs"),
            ),),
        )
        reports = []

        def ingest(report):
            reports.append(report)
            evaluate_report(report, session_id=session.id)

        runtime = module.MoreliaRuntime(manifest=manifest, on_report=ingest)
        runtime._phase = RuntimePhase.RUNNING
        runtime._source_error_queue = Queue()
        yield SimpleNamespace(
            runtime=runtime, clock=clock, reports=reports,
            rows=lambda: db.session.scalars(db.select(RecoveryGap).order_by(RecoveryGap.id)).all(),
        )


def gap_source(gap_scenario, state, at):
    gap_scenario.clock[0] = at
    gap_scenario.runtime._source_error_queue.put({
        "source_id": GAP_DEVICE, "source_port": "COM3", "state": state,
        "timestamp_ns": int(at * 1_000_000_000),
        "failure_kind": "source_read", "exception_type": "OSError",
        "message": "device disconnected", "consecutive_failures": 3,
    })
    gap_scenario.runtime._drain_source_errors()


def gap_report(gap_scenario, at, *, action="none", healthy=False, packets=0, physical=None,
           sample_at=None):
    gap_scenario.clock[0] = at
    detail = {"hardware_present": None}
    if physical is not None:
        detail["disconnect"] = physical
    gap_scenario.runtime._emit_from_watchdog_report({"streams": [{
        "stream_health": "healthy" if healthy else "unhealthy",
        "signals": {
            "worker": {"status": "alive"},
            "heartbeat": {
                "status": "fresh" if packets else "missing",
                "packet_count": packets, "age_sec": 0 if packets else None,
                "last_data_at_epoch": (at if sample_at is None else sample_at) if packets else None,
            },
        },
        "action": {"taken": action, "detail": detail},
    }]})


def gap_begin_long(gap_scenario, at=GAP_START):
    previous_count = len(gap_scenario.rows())
    gap_source(gap_scenario, "degraded", at)
    gap_source(gap_scenario, "degraded", at + 5)
    gap_source(gap_scenario, "recovery_window_expired", at + 10)
    gap_report(gap_scenario, at + 10, action="restart_failed")
    assert len(gap_scenario.rows()) == previous_count


def gap_assert_window(row, start, end, continued):
    assert row.device_id == GAP_DEVICE
    assert row.gap_start == {"timestamp": start}
    assert row.gap_end == {"timestamp": end}
    assert row.details["duration_seconds"] == end - start
    assert row.details["recording_continued"] is continued


def test_unknown_presence_long_disconnect_saves_original_time(gap_scenario):
    gap_begin_long(gap_scenario)
    gap_report(gap_scenario, GAP_START + 23, action="connection_restored", healthy=True, packets=1)
    rows = gap_scenario.rows()
    assert len(rows) == 1
    gap_assert_window(rows[0], GAP_START, GAP_START + 23, False)


def test_ping_only_recovery_waits_for_sample_then_saves_gap(gap_scenario):
    gap_begin_long(gap_scenario)
    gap_report(gap_scenario, GAP_START + 20, action="connection_restored", healthy=True)
    assert gap_scenario.rows() == []
    gap_report(gap_scenario, GAP_START + 23, healthy=True, packets=1)
    rows = gap_scenario.rows()
    assert len(rows) == 1
    gap_assert_window(rows[0], GAP_START, GAP_START + 23, False)


@pytest.mark.parametrize("cached_sample_at", [GAP_START - 1, GAP_START + 10])
def test_cached_healthy_snapshot_cannot_close_long_disconnect(gap_scenario, cached_sample_at):
    gap_begin_long(gap_scenario)
    gap_report(gap_scenario, GAP_START + 20, action="connection_restored", healthy=True,
           packets=100, sample_at=cached_sample_at)
    assert gap_scenario.rows() == []
    gap_report(gap_scenario, GAP_START + 25, healthy=True, packets=1, sample_at=GAP_START + 23)
    rows = gap_scenario.rows()
    assert len(rows) == 1
    gap_assert_window(rows[0], GAP_START, GAP_START + 23, False)


def test_repeated_restore_and_replayed_report_do_not_duplicate_gap(gap_scenario):
    gap_begin_long(gap_scenario)
    gap_report(gap_scenario, GAP_START + 23, action="connection_restored", healthy=True, packets=1)
    healed = gap_scenario.reports[-1]
    evaluate_report(healed, session_id=gap_scenario.runtime._manifest.session_id)
    gap_report(gap_scenario, GAP_START + 24, action="connection_restored", healthy=True, packets=2)
    assert len(gap_scenario.rows()) == 1


def test_two_long_disconnects_keep_separate_episodes(gap_scenario):
    for start in (GAP_START, GAP_START + 100):
        gap_begin_long(gap_scenario, start)
        gap_report(gap_scenario, start + 23, action="connection_restored", healthy=True, packets=1)
    rows = gap_scenario.rows()
    assert len(rows) == 2
    assert rows[0].gap_id != rows[1].gap_id
    gap_assert_window(rows[0], GAP_START, GAP_START + 23, False)
    gap_assert_window(rows[1], GAP_START + 100, GAP_START + 123, False)


def test_old_physical_restore_cannot_replace_later_source_episode(gap_scenario):
    gap_begin_long(gap_scenario)
    old_physical = {
        "episode_id": "old-physical-episode", "started_at": GAP_START,
        "ended_at": GAP_START + 23, "elapsed_sec": 23,
        "recording_continued": False, "reason": "physical disconnect",
    }
    gap_report(gap_scenario, GAP_START + 23, action="connection_restored", healthy=True,
           packets=1, physical=old_physical)
    gap_begin_long(gap_scenario, GAP_START + 100)
    gap_report(gap_scenario, GAP_START + 120, action="connection_restored", healthy=True,
           packets=100, sample_at=GAP_START + 23, physical=old_physical)
    assert len(gap_scenario.rows()) == 1
    gap_report(gap_scenario, GAP_START + 123, action="connection_restored", healthy=True, packets=1)
    rows = gap_scenario.rows()
    assert len(rows) == 2
    assert rows[0].gap_id != rows[1].gap_id
    gap_assert_window(rows[1], GAP_START + 100, GAP_START + 123, False)


def test_short_disconnect_still_records_in_place_recovery(gap_scenario):
    gap_source(gap_scenario, "degraded", GAP_START)
    gap_source(gap_scenario, "recovered", GAP_START + 4.875)
    gap_report(gap_scenario, GAP_START + 4.875, healthy=True, packets=1)
    rows = gap_scenario.rows()
    assert len(rows) == 1
    gap_assert_window(rows[0], GAP_START, GAP_START + 4.875, True)


def test_stale_display_cleanup_preserves_original_outage(gap_scenario):
    gap_source(gap_scenario, "degraded", GAP_START)
    gap_report(gap_scenario, GAP_START + 3600)
    assert gap_scenario.rows() == []
    gap_source(gap_scenario, "recovery_window_expired", GAP_START + 10)
    gap_report(gap_scenario, GAP_START + 3623, action="connection_restored", healthy=True, packets=1)
    rows = gap_scenario.rows()
    assert len(rows) == 1
    gap_assert_window(rows[0], GAP_START, GAP_START + 3623, False)


def test_overlapping_physical_episode_keeps_earliest_source_time_once(gap_scenario):
    gap_begin_long(gap_scenario)
    physical = {
        "episode_id": "physical-episode", "started_at": GAP_START + 2,
        "ended_at": GAP_START + 23, "elapsed_sec": 21,
        "recording_continued": False, "reason": "physical disconnect",
    }
    gap_report(gap_scenario, GAP_START + 23, action="connection_restored", healthy=True,
           packets=1, physical=physical)
    gap_report(gap_scenario, GAP_START + 24, healthy=True, packets=2)
    rows = gap_scenario.rows()
    assert len(rows) == 1
    gap_assert_window(rows[0], GAP_START, GAP_START + 23, False)
