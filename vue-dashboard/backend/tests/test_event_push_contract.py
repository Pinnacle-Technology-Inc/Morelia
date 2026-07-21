"""Contract tests for the northbound push path (packet 7.3).

Three acceptance criteria:
  AC1 — A valid push persists exactly one event and returns its id.
  AC2 — Malformed JSON / unknown field / non-loopback origin / bad token fail closed.
  AC3 — After a simulated plane outage the host re-POSTs unacked entries exactly once.
"""

import pytest

from app.database import transaction
from app.domain.enums import CommsStatus
from app.repositories.backend_events import BackendEventRepository
from app.repositories.sessions import SessionRepository
from app.runtime_child.driver import RuntimePhase, RuntimeReport
from app.runtime_host.server import DataflowRuntimeHost


# ── Helpers ──────────────────────────────────────────────────────────────────

def _session_with_dataflow(app, dataflow_id: str) -> int:
    with app.app_context():
        session = SessionRepository().create({"name": "Push Test"})
        with transaction():
            session.dataflow_id = dataflow_id
        return session.id


def _valid_envelope(dataflow_id: str, sequence: int = 1) -> dict:
    return {
        "protocol_version": "1",
        "report": {
            "dataflow_id": dataflow_id,
            "phase": "running",
            "comms": "current",
            "devices": [],
            "sequence": sequence,
        },
    }


def _make_report(dataflow_id: str, sequence: int) -> RuntimeReport:
    return RuntimeReport(
        dataflow_id=dataflow_id,
        phase=RuntimePhase.RUNNING,
        comms=CommsStatus.CURRENT,
        devices=(),
        sequence=sequence,
    )


class FakePush:
    """Captures push calls; configurable failure mode for outage simulation."""

    def __init__(self, client):
        self.client = client
        self.failing = False
        self.calls: list[dict] = []

    def __call__(self, entry: dict) -> bool:
        self.calls.append(entry)
        if self.failing:
            return False
        resp = self.client.post(
            "/api/v1/internal/events",
            json={"protocol_version": "1", "report": entry},
        )
        return resp.status_code == 202


def _host_with_push(fake_push: FakePush) -> DataflowRuntimeHost:
    """Build a host wired to a FakePush; gate/manifest/driver unused in push tests."""
    return DataflowRuntimeHost(
        gate=None,   # type: ignore[arg-type]
        manifest=None,  # type: ignore[arg-type]
        driver=None,  # type: ignore[arg-type]
        port=0,
        ingest_url="http://plane.internal",  # presence triggers push; actual call via fake_push
        _push_fn=fake_push,
    )


# ── AC1: valid push persists one event and returns its id ─────────────────────

def test_valid_push_returns_202_and_event_id(app, client):
    _session_with_dataflow(app, "df-push-1")

    resp = client.post("/api/v1/internal/events", json=_valid_envelope("df-push-1"))

    assert resp.status_code == 202
    data = resp.get_json()
    assert "event_id" in data
    assert isinstance(data["event_id"], int)


def test_valid_push_persists_exactly_one_event(app, client):
    session_id = _session_with_dataflow(app, "df-push-2")

    resp = client.post("/api/v1/internal/events", json=_valid_envelope("df-push-2"))
    event_id = resp.get_json()["event_id"]

    with app.app_context():
        rows = BackendEventRepository().since(session_id, after_id=0, limit=10)

    assert len(rows) == 1
    assert rows[0].id == event_id
    assert rows[0].dataflow_id == "df-push-2"


# ── AC2: fail-closed cases ─────────────────────────────────────────────────────

def test_non_loopback_origin_returns_403(app, client):
    _session_with_dataflow(app, "df-acl")
    resp = client.post(
        "/api/v1/internal/events",
        json=_valid_envelope("df-acl"),
        environ_base={"REMOTE_ADDR": "10.0.0.1"},
    )
    assert resp.status_code == 403


def test_bad_token_returns_401(app):
    app.config["INGEST_TOKEN"] = "secret-token"
    client = app.test_client()
    _session_with_dataflow(app, "df-token")

    resp = client.post(
        "/api/v1/internal/events",
        json=_valid_envelope("df-token"),
        headers={"X-Agent-Token": "wrong"},
    )
    assert resp.status_code == 401
    app.config["INGEST_TOKEN"] = None


def test_correct_token_accepted(app):
    app.config["INGEST_TOKEN"] = "secret-token"
    client = app.test_client()
    _session_with_dataflow(app, "df-token-ok")

    resp = client.post(
        "/api/v1/internal/events",
        json=_valid_envelope("df-token-ok"),
        headers={"X-Agent-Token": "secret-token"},
    )
    assert resp.status_code == 202
    app.config["INGEST_TOKEN"] = None


def test_malformed_json_returns_400(app, client):
    resp = client.post(
        "/api/v1/internal/events",
        data=b"not json at all",
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_unknown_envelope_field_returns_400(app, client):
    _session_with_dataflow(app, "df-env-unk")
    envelope = {**_valid_envelope("df-env-unk"), "extra": "field"}
    resp = client.post("/api/v1/internal/events", json=envelope)
    assert resp.status_code == 400


def test_wrong_protocol_version_returns_400(app, client):
    resp = client.post(
        "/api/v1/internal/events",
        json={"protocol_version": "9", "report": {}},
    )
    assert resp.status_code == 400


def test_unknown_report_field_returns_400(app, client):
    _session_with_dataflow(app, "df-rep-unk")
    envelope = _valid_envelope("df-rep-unk")
    envelope["report"]["surprise"] = "boom"
    resp = client.post("/api/v1/internal/events", json=envelope)
    assert resp.status_code == 400


def test_unknown_dataflow_returns_404(app, client):
    resp = client.post("/api/v1/internal/events", json=_valid_envelope("df-orphan-7"))
    assert resp.status_code == 404


# ── AC3: ring flush after simulated plane outage ───────────────────────────────

def test_ring_flush_after_outage_lands_once(app, client):
    """Host re-POSTs unacked ring entries after outage; dedup ensures one row each."""
    session_id = _session_with_dataflow(app, "df-retry-7")
    fake_push = FakePush(client)
    host = _host_with_push(fake_push)

    # seq=1: plane up, push succeeds
    with app.app_context():
        host.collect_report(_make_report("df-retry-7", sequence=1))

    # Simulate outage
    fake_push.failing = True
    with app.app_context():
        host.collect_report(_make_report("df-retry-7", sequence=2))

    # Restore; seq=3 triggers flush that re-POSTs seq=2 first
    fake_push.failing = False
    with app.app_context():
        host.collect_report(_make_report("df-retry-7", sequence=3))

    with app.app_context():
        rows = BackendEventRepository().since(session_id, after_id=0, limit=100)

    assert {r.sequence for r in rows} == {1, 2, 3}
    assert len(rows) == 3  # dedup: no duplicates


def test_ring_flush_dedup_on_double_push(app, client):
    """Pushing the same (dataflow_id, sequence) twice lands exactly one row."""
    session_id = _session_with_dataflow(app, "df-dedup-7")
    envelope = _valid_envelope("df-dedup-7", sequence=10)

    first = client.post("/api/v1/internal/events", json=envelope)
    second = client.post("/api/v1/internal/events", json=envelope)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.get_json()["event_id"] == second.get_json()["event_id"]

    with app.app_context():
        rows = BackendEventRepository().since(session_id, after_id=0, limit=10)
    assert len(rows) == 1
