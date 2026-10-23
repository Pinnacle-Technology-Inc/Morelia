import io
import json
from types import SimpleNamespace

import pytest

from app.logging_config import configure_logging
from Morelia.Watchdog.watchdog import Watchdog


class Device:
    def __init__(self, port, failure=None):
        self.port = port
        self.failure = failure
        self._port = None

    def open_port(self):
        if self.failure == "open":
            raise OSError("device is busy")
        self._port = object()

    def close_port(self):
        self._port = None

    def write_packet(self, *args):
        pass

    def read_pod_packet(self, **kwargs):
        raise TimeoutError("quiet")

    def write_read(self, **kwargs):
        if self.failure == "timeout":
            raise TimeoutError("GET SAMPLE RATE timed out")
        return SimpleNamespace(payload=(0 if self.failure == "invalid" else 2000,))


@pytest.mark.parametrize("require_ready", [True, False])
def test_preflight_failure_reasons_reach_session_diagnostic_file(tmp_path, require_ready):
    configure_logging(
        SimpleNamespace(LOG_LEVEL="INFO", LOG_FORMAT="json", DIAGNOSTIC_LOG_DIR=tmp_path),
        stream=io.StringIO(),
        diagnostic_layer="watchdog-driver",
        diagnostic_context={"session_id": 18, "watchdog_id": "watchdog-test"},
    )
    watchdog = Watchdog(devices=[
        Device("AB0MZ1AE", "open"),
        Device("AB0MZ1AY", "timeout"),
        Device("AB0MZ1AZ", "invalid"),
        Device("healthy"),
    ])

    if require_ready:
        with pytest.raises(RuntimeError) as raised:
            watchdog.preflight()
        assert str(raised.value) == "preflight failed for ['AB0MZ1AE', 'AB0MZ1AY', 'AB0MZ1AZ']"
    else:
        assert watchdog.preflight(require_ready=False)["ok"] is False

    path = tmp_path / "session-18" / "watchdog-driver.jsonl"
    assert path.exists(), "Preflight failures must be written to the session diagnostic file"
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert [(e["port"], e["reason"], e["attempt"]) for e in events] == [
        ("AB0MZ1AE", "open_port: device is busy", 0),
        ("AB0MZ1AY", "GET SAMPLE RATE timed out", 3),
        ("AB0MZ1AZ", "GET SAMPLE RATE returned an invalid value.", 3),
    ]
    assert all(e["event"] == "device preflight failed" for e in events)
    assert all(e["level"] == "error" and e["action"] == "preflight" for e in events)
    assert all(e["session_id"] == 18 and e["watchdog_id"] == "watchdog-test" for e in events)
