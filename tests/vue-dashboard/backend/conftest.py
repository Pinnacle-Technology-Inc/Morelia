import logging

import pytest
import structlog

from app import create_app
from app.config import TestingConfig
from app.database import db
from app.logging_config import configure_logging

@pytest.fixture(autouse=True)
def reset_logging():

    root = logging.getLogger()
    werkzeug = logging.getLogger("werkzeug")

    # --- snapshot ---
    saved_root_handlers = root.handlers[:]
    saved_root_level = root.level
    saved_root_disabled = root.disabled
    saved_werkzeug_handlers = werkzeug.handlers[:]
    saved_werkzeug_propagate = werkzeug.propagate
    saved_werkzeug_level = werkzeug.level
    saved_structlog = structlog.get_config()

    configure_logging(TestingConfig)
    yield

    # --- restore ---
    root.handlers[:] = saved_root_handlers
    root.setLevel(saved_root_level)
    root.disabled = saved_root_disabled

    werkzeug.handlers[:] = saved_werkzeug_handlers
    werkzeug.propagate = saved_werkzeug_propagate
    werkzeug.setLevel(saved_werkzeug_level)

    structlog.reset_defaults()
    structlog.configure(**saved_structlog)


@pytest.fixture
def app(tmp_path):
    """A fresh app built with the testing profile, one per test that needs it."""
    database_path = tmp_path / "test.sqlite3"
    app = create_app(
        "testing",
        config_overrides={
            "DEVICE_TEMPLATE_DIR": str(tmp_path / "device-templates"),
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
        },
    )
    with app.app_context():
        db.create_all()
    return app


@pytest.fixture
def client(app):
    """A test client that sends fake requests in-process (no real network).

    Note `client` depends on `app` simply by naming it as a parameter — that's
    pytest's fixture dependency injection.
    """
    return app.test_client()

@pytest.fixture(autouse=True)
def cleanup_multiprocessing():
    yield

    import gc
    import multiprocessing

    gc.collect()

    for child in multiprocessing.active_children():
        if child.is_alive():
            child.terminate()
            child.join(timeout=2)