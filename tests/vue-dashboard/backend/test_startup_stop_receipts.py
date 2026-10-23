"""A failed startup can finish teardown before its control server disappears."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.control.supervisor import HostSupervisor
from app.domain.errors import StopProofMissing


@pytest.mark.parametrize("integrity", [True, False])
def test_dead_startup_uses_retained_shutdown_receipt_before_live_probe(monkeypatch, integrity):
    from app.watchdog_process import control

    supervisor = HostSupervisor()
    owner = SimpleNamespace(runtime_id="runtime", watchdog_id="watchdog",
                            dataflow_id="flow", watchdog_control_port=None, token=None)
    payload = {"command_id": "original-failure", "stop_reason": "runtime_failure",
               "teardown_confirmed": True, "output_integrity_confirmed": integrity}
    report = SimpleNamespace(envelope=SimpleNamespace(
        watchdog_id="watchdog", event_type="runtime.stop_finished", payload=payload,
    ))
    supervisor._lifecycle_reports = Mock(return_value=[("outbox", report)])
    supervisor._ownerships = Mock()
    client = Mock(side_effect=AssertionError("Exited startup has no live control peer"))
    monkeypatch.setattr(control, "WatchdogControlClient", client)
    assert supervisor._stop_starting_watchdog(None, owner, None) == payload
    client.assert_not_called()
    supervisor._ownerships.mark_stopping.assert_not_called()


@pytest.mark.parametrize("watchdog,teardown", [("different-watchdog", True), ("watchdog", False)])
def test_missing_current_teardown_evidence_does_not_release_dead_startup(watchdog, teardown):
    supervisor = HostSupervisor()
    owner = SimpleNamespace(runtime_id="runtime", watchdog_id="watchdog",
                            dataflow_id="flow", watchdog_control_port=None, token=None)
    report = SimpleNamespace(envelope=SimpleNamespace(
        watchdog_id=watchdog, event_type="runtime.stop_finished",
        payload={"teardown_confirmed": teardown},
    ))
    supervisor._lifecycle_reports = Mock(return_value=[("outbox", report)])
    supervisor._ownerships = Mock()
    with pytest.raises(StopProofMissing):
        supervisor._stop_starting_watchdog(None, owner, None)
