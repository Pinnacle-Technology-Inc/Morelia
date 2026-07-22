"""Application factory.

Importing this package does NOT create an app — it only defines how to build
one. Callers (the Flask dev server, pytest, a production WSGI server) each call
``create_app(...)`` to get an instance wired for their environment.
"""

from pathlib import Path

from dotenv import load_dotenv

# Every entrypoint (Flask app, `pinnacle` CLI, the runtime-host subprocess)
# imports something under `app.*`, which runs this package's __init__ first —
# so loading local config here, before any other app import, is the one place
# that guarantees it lands before Config classes read os.environ at import time.
#
# Precedence (highest first):
#   1. real process environment
#   2. `.env` — secrets and machine-local paths
#   3. `settings.toml` — portable non-secret knobs
#   4. code defaults in app.config.Config
#
# override=False on both loaders: a higher layer always wins.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND_ROOT / ".env", override=False)

from app.settings_file import default_settings_path, load_settings_file  # noqa: E402

load_settings_file(default_settings_path(_BACKEND_ROOT), override=False)

from flask import Flask  # noqa: E402 - must follow local config loads above
from flask_smorest import Api  # noqa: E402

from app.config import get_config  # noqa: E402
from app.database import init_database  # noqa: E402
from app.errors import register_error_handlers  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.request_logging import register_request_logging  # noqa: E402


def create_app(
    config_name: str | None = None,
    config_overrides: dict | None = None,
) -> Flask:
    """Build and configure a Flask application instance.

    Args:
        config_name: "development", "testing", or "production". When omitted,
            falls back to the FLASK_CONFIG env var, then "development".
        config_overrides: Optional settings applied after the selected profile.
            Intended for isolated tests and deployment-specific configuration.

    Returns:
        A fully configured Flask app with all blueprints registered.
    """
    config = get_config(config_name)
    configure_logging(config)
    app = Flask(__name__)
    app.config.from_object(config)
    if config_overrides:
        app.config.update(config_overrides)

    # Fail loudly at boot if a profile left a required secret unset.
    # Dev/testing inherit a default, so this only bites the production profile.
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("SECRET_KEY must be set (e.g. via the environment).")

    # Flask-SQLAlchemy reads configuration exactly once during init_app(), so
    # profiles and caller overrides must be loaded first.
    # Source: https://flask-sqlalchemy.palletsprojects.com/en/stable/config/
    init_database(app)

    api = Api(app)

    register_request_logging(app)
    # this overrides flask-smorest's default error format (last handler wins).
    register_error_handlers(app)
    # Operational endpoints: unversioned, and deliberately NOT part of the
    # business API contract — monitors expect a stable /health path forever.
    from app.health import health_bp

    app.register_blueprint(health_bp)

    # Versioned business API: registered on `api` so it lands in the OpenAPI
    # spec. The reference `sessions` resource in app/api/ embodies the
    # conventions every future resource copies.
    from app.api import register_routes
    from app.control.control_plane_state import ControlPlaneState

    app.extensions["control_plane_state"] = ControlPlaneState()

    register_routes(api, app)

    # Live browser Plot data plane (packet 27): text/event-stream, so registered
    # directly on the app (off the JSON-centric OpenAPI spec), and paired with a
    # per-app bounded fan-out broker so each app instance owns isolated state.
    from app.api.plot_stream import PlotBroker, blp as plot_stream_bp

    app.extensions["plot_broker"] = PlotBroker()
    app.register_blueprint(plot_stream_bp)

    from app.cli import register_cli

    register_cli(app)

    if app.config["STARTUP_RECONCILIATION_ENABLED"]:
        from app.repositories.sessions import SessionRepository
        from app.services.reconciliation import (
            reconcile_startup_if_tables_exist,
            reconciliation_tables_ready,
        )

        with app.app_context():
            host_supervisor = app.extensions.get("host_supervisor")
            if app.config.get("STARTUP_RECONCILIATION_ADOPT_ONLY"):
                if not reconciliation_tables_ready():
                    app.extensions["restart_reconciliation_report"] = {
                        "adopted": [],
                        "uncertain": [],
                    }
                    return app
                sessions = SessionRepository().with_runtime_host_identity()
                report = (
                    host_supervisor.reconcile(sessions, adopt_only=True)
                    if host_supervisor is not None
                    else {"adopted": [], "uncertain": []}
                )
                app.extensions["restart_reconciliation_report"] = report
                return app

            summary = reconcile_startup_if_tables_exist(
                status_probe=app.config["STARTUP_RECONCILIATION_STATUS_PROBE"]
            )
            # DB-only reconciliation above updates RuntimeOwnership/Operation rows;
            # it never touches HostSupervisor's in-process `_children` registry.
            # Without this, any daemon restart while a session is running leaves
            # `_children` empty for that dataflow forever, and stop()/dispatch()
            # fail every retry until this runs.
            if summary is not None and host_supervisor is not None:
                host_supervisor.reconcile(SessionRepository().with_runtime_host_identity())

    return app
