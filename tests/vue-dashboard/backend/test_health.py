"""Tests for the health-check endpoints.

These assert a *contract* (status code + a couple of stable keys), not the
exact shape of the whole payload — so you can enrich the responses later
without rewriting the tests. A good test pins down behavior you promise to
callers, and leaves room for behavior you don't.
"""


def test_health_reports_ok(client):
    """Liveness returns 200 with status "ok"."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_ready_returns_a_readiness_verdict(client):
    """Readiness returns JSON with a boolean `ready` flag.

    With no dependency checks wired up yet, the service reports ready (200).
    Once you add real checks, expand this test to cover the not-ready (503)
    path too.
    """
    response = client.get("/ready")
    body = response.get_json()

    assert response.status_code == 200
    assert isinstance(body["ready"], bool)
