"""Opt-in gate for the hardware tier.

These tests are skipped by default so they never turn the fast suite red or
green on their own. Enable them explicitly at a checkpoint:

    RUN_HARDWARE=1 venv\\Scripts\\python.exe -m pytest tests/hardware -v

Or from PowerShell:

    $env:RUN_HARDWARE = "1"; venv\\Scripts\\python.exe -m pytest tests/hardware -v
"""

import os

import pytest

_HARDWARE_ENABLED = os.environ.get("RUN_HARDWARE") == "1"


def pytest_collection_modifyitems(config, items):
    if _HARDWARE_ENABLED:
        return
    skip = pytest.mark.skip(reason="hardware tier: set RUN_HARDWARE=1 to enable")
    for item in items:
        item.add_marker(skip)
