from __future__ import annotations

import json
import time

import pytest
from click.testing import CliRunner

from app.cli.main import pinnacle

@pytest.fixture(scope="function")
def running_daemon():
    runner = CliRunner()

    runner.invoke(pinnacle, ["start"])

    try:
        yield runner

    finally:
        runner.invoke(pinnacle, ["shutdown"])
        wait_for_shutdown(runner)

def test_status_running(running_daemon):
    check_status(
        running_daemon=running_daemon,
        running=True,
        serving=False,
    )

def test_doctor_cmd(running_daemon):
    result = running_daemon.invoke(pinnacle, ["doctor"])

    assert result.output is not None
    assert result.output != ""
    check_result(result=result)

def check_status(running_daemon, running: bool, serving: bool):
    result = running_daemon.invoke(pinnacle, ["status"])

    check_result(result=result)

    status = json.loads(result.output)

    assert status["running"] is running
    assert status["serving"] is serving

def check_result(result):
    assert result.exit_code == 0
    assert result.exception is None

def wait_for_shutdown(runner, timeout=5):
    start = time.time()

    while time.time() - start < timeout:
        result = runner.invoke(pinnacle, ["status"])

        if result.exit_code != 0:
            return

        try:
            status = json.loads(result.output)
            if not status.get("running", False):
                return
        except json.JSONDecodeError:
            pass

        time.sleep(0.1)

    raise TimeoutError("Daemon did not shut down")