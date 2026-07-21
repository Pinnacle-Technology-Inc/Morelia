"""Shared pytest fixtures.

`conftest.py` is auto-discovered by pytest — any fixture defined here is
available to every test in this directory without importing it. This is where
the application factory pays off: each test gets a freshly built app in the
"testing" profile, fully isolated from dev/prod settings.
"""

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
def app():
    """A fresh app built with the testing profile, one per test that needs it."""
    app = create_app("testing")
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
