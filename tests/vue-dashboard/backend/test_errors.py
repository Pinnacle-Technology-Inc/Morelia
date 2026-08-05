"""Contract tests for the consistent error format (RFC 9457).

This file currently covers the 404 path only — it's the cheapest error to
trigger (any unknown URL) and it proves the important thing: that our
problem+json handler overrides flask-smorest's default error shape. Once the
reference resource exists, we'll add 400/409/422/423 here too.
"""


def test_unknown_route_returns_problem_json(client):
    """An unknown URL yields our RFC 9457 body, not flask-smorest's default."""
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    # The +json suffix is the giveaway that our handler ran, not the default.
    assert response.content_type == "application/problem+json"

    body = response.get_json(force=True)
    assert body["status"] == 404
    assert body["code"] == "not_found"      # stable machine-readable key
    assert body["title"] == "Not Found"     # human label
    assert "detail" in body                 # human specifics
    assert body["instance"] == "/api/v1/does-not-exist"
