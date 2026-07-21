from app.domain.enums import GapConfidence, IncidentStatus
from app.repositories.incidents import IncidentRepository
from app.repositories.recovery_gaps import RecoveryGapRepository
from app.repositories.sessions import SessionRepository


def _session_id(app) -> int:
    with app.app_context():
        return SessionRepository().create({"name": "Incident Session"}).id


def test_incident_repository_creates_lists_acknowledges_and_resolves(app):
    session_id = _session_id(app)
    incidents = IncidentRepository()

    with app.app_context():
        incident = incidents.create(
            incident_id="inc-1",
            session_id=session_id,
            dataflow_id="df-1",
            device_id="dev-a",
            sink_id="sink-a",
            runtime_id="runtime-1",
            operation_id="op-1",
            recovery_id="rec-1",
            reason="stream unhealthy",
            policy="recommend",
            details={"stream_status": "unhealthy"},
        )

        assert incident.status == IncidentStatus.OPEN.value
        assert incident.details == {"stream_status": "unhealthy"}
        assert [row.incident_id for row in incidents.list_for_session(session_id)] == ["inc-1"]

        acknowledged = incidents.acknowledge(
            "inc-1",
            acknowledged_by="operator@example.com",
            note="checking cable",
        )
        assert acknowledged.status == IncidentStatus.ACKNOWLEDGED.value
        assert acknowledged.acknowledged_at is not None
        assert acknowledged.acknowledged_by == "operator@example.com"

        resolved = incidents.resolve("inc-1", resolution="reconnected")
        assert resolved.status == IncidentStatus.RESOLVED.value
        assert resolved.resolved_at is not None
        assert resolved.resolution == "reconnected"


def test_recovery_gap_repository_links_gap_to_incident(app):
    session_id = _session_id(app)
    incidents = IncidentRepository()
    gaps = RecoveryGapRepository()

    with app.app_context():
        incident = incidents.create(
            incident_id="inc-gap-1",
            session_id=session_id,
            dataflow_id="df-1",
            device_id="dev-b",
            reason="manual recovery started",
        )

        gap = gaps.create(
            gap_id="gap-1",
            incident_id=incident.incident_id,
            session_id=session_id,
            dataflow_id="df-1",
            device_id="dev-b",
            sink_id="sink-b",
            operation_id="op-recover-1",
            recovery_id="rec-gap-1",
            previous_segment_id="seg-before",
            next_segment_id="seg-after",
            reason="stream reset",
            policy="automate",
            confidence=GapConfidence.UNCERTAIN,
            gap_start={"row": 42},
            gap_end={"row": 43},
            details={"note": "continuity cannot be proven"},
        )

        assert gap.confidence == GapConfidence.UNCERTAIN.value
        assert gap.gap_start == {"row": 42}
        assert gap.gap_end == {"row": 43}
        assert gaps.get("gap-1").incident_id == "inc-gap-1"
        assert [row.gap_id for row in gaps.list_for_session(session_id)] == ["gap-1"]
        assert [row.gap_id for row in gaps.list_for_incident("inc-gap-1")] == ["gap-1"]
