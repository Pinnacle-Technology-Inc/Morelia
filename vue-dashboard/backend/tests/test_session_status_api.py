"""API coverage for the fleet overview (6f) and detail snapshot (6g)."""

from app.database import db
from app.domain.enums import GapConfidence, SessionStatus
from app.models.output_file import OutputFile
from app.models.session import Session
from app.repositories.backend_events import BackendEventRepository
from app.repositories.incidents import IncidentRepository
from app.repositories.recovery_gaps import RecoveryGapRepository
from app.repositories.runtime_ownership import RuntimeOwnershipRepository
from app.services.operations import create_operation


def _seed_report(session_id: int, dataflow_id: str, *, stream_status: str) -> None:
    BackendEventRepository().append(
        event_type="runtime.report",
        session_id=session_id,
        dataflow_id=dataflow_id,
        sequence=1,
        payload={"devices": [{"device_id": "dev-a", "stream_status": stream_status}]},
        phase="running",
        comms="current",
    )


def _sink(source_id: str, sink_id: str, **overrides) -> dict:
    """A per-sink live snapshot payload as a report carries it (SinkReport.to_dict)."""
    snapshot = {
        "source_id": source_id,
        "sink_id": sink_id,
        "sink_class": "csv",
        "health": "healthy",
        "delivery": "delivered",
        "sequence": 3,
        "state_timestamp_ns": 1,
        "buffered_samples": 0,
        "buffered_bytes": 0,
        "sample_loss": 0,
        "byte_loss": 0,
    }
    snapshot.update(overrides)
    return snapshot


def _seed_report_with_sinks(
    session_id: int, dataflow_id: str, *, stream_status: str, sinks: list[dict]
) -> None:
    BackendEventRepository().append(
        event_type="runtime.report",
        session_id=session_id,
        dataflow_id=dataflow_id,
        sequence=1,
        payload={
            "devices": [{"device_id": "dev-a", "stream_status": stream_status}],
            "sinks": sinks,
        },
        phase="running",
        comms="current",
    )


def test_fleet_overview_counts_running_and_reports_phase(client, app):
    with app.app_context():
        db.session.add(Session(id=1, name="alpha", status=SessionStatus.ACTIVE, dataflow_id="df-1"))
        db.session.add(Session(id=2, name="beta", status=SessionStatus.DRAFT))
        db.session.add(
            Session(id=3, name="gamma", status=SessionStatus.COMPLETED, dataflow_id="df-3")
        )
        db.session.commit()
        _seed_report(1, "df-1", stream_status="healthy")

    response = client.get("/api/v1/sessions/overview")

    assert response.status_code == 200
    body = response.get_json()
    assert body["running_count"] == 1
    assert body["total_count"] == 3
    rows = {row["id"]: row for row in body["sessions"]}
    assert rows[1]["status"] == "active"
    assert rows[1]["phase"] == "running"
    # No live poller in tests, so health is reported as None rather than guessed.
    assert rows[1]["health"] is None
    # A session with no persisted report has no phase.
    assert rows[2]["phase"] is None


def test_status_snapshot_joins_history_and_hides_suspect(client, app):
    with app.app_context():
        db.session.add(Session(id=7, name="snap", status=SessionStatus.ACTIVE, dataflow_id="df-7"))
        db.session.commit()
        # A suspect stream must surface as healthy (suspect-hidden rule).
        _seed_report(7, "df-7", stream_status="suspect")
        RuntimeOwnershipRepository().create_starting(
            runtime_id="rt-7",
            session_id=7,
            dataflow_id="df-7",
            manifest_hash="hash-7",
            token=None,
        )
        create_operation(
            session_id=7,
            dataflow_id="df-7",
            command="start",
            request_key="req-7",
        )
        IncidentRepository().create(
            incident_id="inc-7",
            session_id=7,
            dataflow_id="df-7",
            device_id="dev-a",
            reason="stream unhealthy",
        )
        RecoveryGapRepository().create(
            gap_id="gap-7",
            session_id=7,
            dataflow_id="df-7",
            device_id="dev-a",
            reason="stream recovered",
            confidence=GapConfidence.UNCERTAIN,
        )

    response = client.get("/api/v1/sessions/7/status")

    assert response.status_code == 200
    body = response.get_json()
    assert body["session"]["id"] == "7"
    assert body["session"]["status"] == "active"
    assert body["phase"] == "running"
    assert body["latest_report"]["devices"] == [
        {"device_id": "dev-a", "stream_status": "healthy"}
    ]
    assert [rt["runtime_id"] for rt in body["runtimes"]] == ["rt-7"]
    assert [op["command"] for op in body["operations"]] == ["start"]
    assert [inc["incident_id"] for inc in body["incidents"]] == ["inc-7"]
    assert [gap["gap_id"] for gap in body["gaps"]] == ["gap-7"]
    # The runtime never claimed a watchdog identity — the "active runtime"
    # view still surfaces its runtime_id, but no watchdog fields yet, and no
    # direct watchdog-process telemetry has ever arrived for this session.
    assert body["runtime_id"] == "rt-7"
    assert body["watchdog_id"] is None
    assert body["watchdog_state"] is None
    assert body["last_report_at"] is None
    assert body["outbox_health"] == "unknown"


def test_status_snapshot_surfaces_active_watchdog_identity_and_outbox_health(client, app):
    with app.app_context():
        db.session.add(Session(id=8, name="wd-snap", status=SessionStatus.ACTIVE, dataflow_id="df-8"))
        db.session.commit()
        RuntimeOwnershipRepository().create_starting(
            runtime_id="rt-8",
            session_id=8,
            dataflow_id="df-8",
            manifest_hash="hash-8",
            token=None,
        )
        RuntimeOwnershipRepository().set_watchdog("rt-8", watchdog_id="wd-8")
        BackendEventRepository().append(
            event_type="runtime.report",
            session_id=8,
            dataflow_id="df-8",
            payload={"devices": []},
            runtime_id="rt-8",
            watchdog_id="wd-8",
            report_id="wd-8:0",
        )

    response = client.get("/api/v1/sessions/8/status")

    assert response.status_code == 200
    body = response.get_json()
    assert body["runtime_id"] == "rt-8"
    assert body["watchdog_id"] == "wd-8"
    # set_watchdog() claims a fresh watchdog identity in STARTING state; it
    # only reaches RUNNING via a later update_watchdog_seen() heartbeat.
    assert body["watchdog_state"] == "starting"
    assert body["last_report_at"] is not None
    # Freshly seeded telemetry, no clock advance — well within the default
    # freshness window.
    assert body["outbox_health"] == "current"


def test_status_snapshot_explains_automatic_recovery_retry(client, app):
    with app.app_context():
        db.session.add(
            Session(id=9, name="recovering", status=SessionStatus.ACTIVE, dataflow_id="df-9")
        )
        db.session.commit()
        repo = RuntimeOwnershipRepository()
        repo.create_starting(
            runtime_id="rt-9",
            session_id=9,
            dataflow_id="df-9",
            manifest_hash="hash-9",
            token="token-9",
        )
        repo.mark_recovering(
            "rt-9",
            phase="retry_wait",
            reason="watchdog_authentication_probe_failed",
            attempt=2,
            next_retry_at="2026-07-16T15:31:00+00:00",
            evidence={"pid_alive": True, "identity_verified": False},
        )

    body = client.get("/api/v1/sessions/9/status").get_json()

    assert body["recovery"]["phase"] == "retry_wait"
    assert body["recovery"]["hardware_access"] == "blocked"
    assert body["recovery"]["attempt"] == 2
    assert "retrying" in body["recovery"]["operator_message"].lower()


def test_status_snapshot_unknown_session_returns_404(client):
    response = client.get("/api/v1/sessions/999/status")

    assert response.status_code == 404
    assert response.get_json(force=True)["code"] == "session_not_found"


def test_status_reports_sibling_sinks_independently_of_healthy_source(client, app):
    """A running/healthy source coexists with degraded, failed, buffering, and
    finalizing sibling sinks — each on its own axis, none folded into source
    health (gaps SINK-08/SINK-23)."""
    with app.app_context():
        db.session.add(
            Session(id=30, name="multi", status=SessionStatus.ACTIVE, dataflow_id="df-30")
        )
        db.session.commit()
        _seed_report_with_sinks(
            30,
            "df-30",
            stream_status="healthy",
            sinks=[
                _sink("dev-a", "sink-csv", health="healthy", delivery="delivered"),
                _sink(
                    "dev-a",
                    "sink-influx",
                    sink_class="influx",
                    health="degraded",
                    delivery="delivering",
                    buffered_samples=120,
                    buffered_bytes=4096,
                ),
                _sink(
                    "dev-a",
                    "sink-quest",
                    sink_class="quest",
                    health="failed",
                    delivery="failed",
                    sample_loss=17,
                    byte_loss=340,
                    component="outbox-client",
                    failure_kind="sink_write",
                    exception_type="ConnectionError",
                    message="destination refused connection",
                    last_success_seq=9,
                ),
                _sink(
                    "dev-a",
                    "sink-edf",
                    sink_class="edf",
                    health="healthy",
                    delivery="delivered",
                    finalization="finalizing",
                    component="pvfs-writer",
                ),
            ],
        )

    body = client.get("/api/v1/sessions/30/status").get_json()

    # Source axis untouched: healthy source, running phase — NOT derived from the
    # worst (failed) sink.
    assert body["phase"] == "running"
    assert body["latest_report"]["devices"] == [
        {"device_id": "dev-a", "stream_status": "healthy"}
    ]

    sinks = {s["sink_id"]: s for s in body["sinks"]}
    assert set(sinks) == {"sink-csv", "sink-influx", "sink-quest", "sink-edf"}
    # Every sink carries its owning source identity, kept separate.
    assert all(s["source_id"] == "dev-a" for s in sinks.values())
    # All four states are simultaneously representable.
    assert sinks["sink-csv"]["health"] == "healthy"
    assert sinks["sink-influx"]["health"] == "degraded"
    assert sinks["sink-influx"]["delivery"] == "delivering"
    assert sinks["sink-influx"]["buffered_samples"] == 120
    assert sinks["sink-quest"]["health"] == "failed"
    assert sinks["sink-edf"]["finalization"] == "finalizing"
    # Present in the live report => current, distinguishable from a stale sink.
    assert all(s["status"] == "current" for s in sinks.values())


def test_status_sink_loss_is_explicit_and_diagnostics_redacted(client, app):
    with app.app_context():
        db.session.add(
            Session(id=31, name="lossy", status=SessionStatus.ACTIVE, dataflow_id="df-31")
        )
        db.session.commit()
        _seed_report_with_sinks(
            31,
            "df-31",
            stream_status="healthy",
            sinks=[
                _sink(
                    "dev-a",
                    "sink-quest",
                    sink_class="quest",
                    health="failed",
                    delivery="failed",
                    sample_loss=42,
                    byte_loss=1024,
                    failure_kind="sink_write",
                    exception_type="TimeoutError",
                    message="write timed out",
                    last_success_seq=7,
                )
            ],
        )

    body = client.get("/api/v1/sessions/31/status").get_json()
    sink = body["sinks"][0]

    # Loss is explicit and reported as-is (monotonic counters from the wire).
    assert sink["sample_loss"] == 42
    assert sink["byte_loss"] == 1024
    # Diagnostics are the bounded redacted set — no raw samples/tokens/credentials.
    assert sink["diagnostics"] == {
        "failure_kind": "sink_write",
        "exception_type": "TimeoutError",
        "message": "write timed out",
        "last_success_seq": 7,
    }


def test_status_sink_open_incident_and_durable_output_surface_together(client, app):
    """Open per-sink incident and durable output_files evidence attach to the same
    sink identity; a source-scoped incident stays off the sink axis."""
    with app.app_context():
        db.session.add(
            Session(id=32, name="durable", status=SessionStatus.ACTIVE, dataflow_id="df-32")
        )
        db.session.commit()
        _seed_report_with_sinks(
            32,
            "df-32",
            stream_status="healthy",
            sinks=[
                _sink(
                    "dev-a",
                    "sink-quest",
                    sink_class="quest",
                    health="failed",
                    delivery="failed",
                    sample_loss=5,
                    byte_loss=80,
                )
            ],
        )
        # Per-sink incident (device_id = owning source, sink_id set).
        IncidentRepository().create(
            incident_id="inc-sink-32",
            session_id=32,
            dataflow_id="df-32",
            device_id="dev-a",
            sink_id="sink-quest",
            reason="sink failed",
            details={"health": "failed", "delivery": "failed"},
        )
        # Source-scoped incident (sink_id NULL) must NOT land on the sink axis.
        IncidentRepository().create(
            incident_id="inc-src-32",
            session_id=32,
            dataflow_id="df-32",
            device_id="dev-a",
            reason="stream unhealthy",
        )
        # Durable output evidence for the sink.
        db.session.add(
            OutputFile(
                output_id="out-32",
                logical_sink_id="lsink-32",
                segment_index=0,
                session_id=32,
                dataflow_id="df-32",
                device_id="dev-a",
                sink_id="sink-quest",
                sink_type="quest",
                path="/data/df-32/sink-quest.part",
                delivery_state="failed",
                artifact_state="merge_failed",
                sample_loss=9,
                byte_loss=200,
            )
        )
        db.session.commit()

    body = client.get("/api/v1/sessions/32/status").get_json()
    sink = next(s for s in body["sinks"] if s["sink_id"] == "sink-quest")

    # Only the sink-scoped incident is attached here.
    assert [i["incident_id"] for i in sink["open_incidents"]] == ["inc-sink-32"]
    # Durable output evidence surfaces on its own sub-object with its provenance.
    assert sink["output"]["artifact_state"] == "merge_failed"
    assert sink["output"]["delivery_state"] == "failed"
    assert sink["output"]["logical_sink_id"] == "lsink-32"
    assert sink["output"]["sample_loss"] == 9
    assert sink["output"]["byte_loss"] == 200


def test_status_sink_known_only_from_durable_evidence_is_stale(client, app):
    """A sink with an open incident but no live report snapshot reports ``stale``
    (health None) — distinguishable from a healthy live sink."""
    with app.app_context():
        db.session.add(
            Session(id=33, name="stale", status=SessionStatus.ACTIVE, dataflow_id="df-33")
        )
        db.session.commit()
        # No report carrying this sink; only a durable incident.
        IncidentRepository().create(
            incident_id="inc-stale-33",
            session_id=33,
            dataflow_id="df-33",
            device_id="dev-a",
            sink_id="sink-gone",
            reason="sink failed",
        )

    body = client.get("/api/v1/sessions/33/status").get_json()
    sink = next(s for s in body["sinks"] if s["sink_id"] == "sink-gone")

    assert sink["status"] == "stale"
    assert sink["health"] is None
    assert sink["last_update"] is None
    assert [i["incident_id"] for i in sink["open_incidents"]] == ["inc-stale-33"]


def test_status_snapshot_has_empty_sinks_when_none_reported(client, app):
    with app.app_context():
        db.session.add(
            Session(id=34, name="nosinks", status=SessionStatus.ACTIVE, dataflow_id="df-34")
        )
        db.session.commit()
        _seed_report(34, "df-34", stream_status="healthy")

    body = client.get("/api/v1/sessions/34/status").get_json()
    assert body["sinks"] == []
