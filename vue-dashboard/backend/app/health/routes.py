"""Health-check endpoints.

This dashboard's whole job is to report on the health of *other* things, so its
own health surface is the first thing a monitor, smoke test, or the Vue client
will probe. Keep these endpoints cheap and predictable.

Two distinct questions, two endpoints:
  - GET /health  -> liveness:  "is this process up and serving HTTP?"
  - GET /ready   -> readiness: "is it ready to do real work right now?"
"""

from flask import Blueprint, jsonify

# A Blueprint groups related routes so the factory can register them as a unit.
# The name "health" namespaces the endpoints (e.g. url_for("health.health")).
health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def health():
    """Liveness probe.

    Deliberately checks *nothing* external. It answers only "is this Flask
    process alive and able to return a response?" — so a slow database or an
    unreachable watchdog can never make a live process look dead.
    """
    return jsonify(status="ok")


@health_bp.get("/ready")
def ready():
    """Readiness probe.

    Unlike liveness, readiness MAY inspect the things this service depends on
    to do useful work, and reports 503 (Service Unavailable) when one is down
    so a client/orchestrator stops sending real traffic — without killing the
    process the way a failed liveness check would.

    TODO(you): decide what "ready" means for THIS system and fill in `checks`.
    See the message in the chat for the trade-offs and candidate checks.
    """
    # Each entry maps a dependency name -> True (healthy) / False (down).
    # all({}) is True, so with no checks this safely reports "ready".
    checks: dict[str, bool] = {}

    is_ready = all(checks.values())
    status_code = 200 if is_ready else 503
    return jsonify(ready=is_ready, checks=checks), status_code
