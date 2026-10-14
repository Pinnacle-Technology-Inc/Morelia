"""CLI boundary checks: connection-only writes and passive native diagnostics."""

from copy import deepcopy
import importlib
import json
import sys
from types import ModuleType

from click.testing import CliRunner
import pytest

from app.cli.main import pinnacle


class RecordingDaemon:
    def __init__(self, row):
        self.row = deepcopy(row)
        self.calls = []

    def get(self, path):
        self.calls.append(("GET", path, None))
        if path == "/api/v1/device-configs":
            return [deepcopy(self.row)]
        assert path == "/api/v1/device-configs/17"
        return deepcopy(self.row)

    def patch(self, path, payload):
        self.calls.append(("PATCH", path, deepcopy(payload)))
        assert path == "/api/v1/device-configs/17"
        return {**deepcopy(self.row), **deepcopy(payload)}


@pytest.fixture
def saved_config():
    return {
        "id": 17,
        "nickname": "left-pod",
        "hardware_id": "FT12345A",
        "type": "pod8206hr",
        "parameters": {"preamp_gain": 10, "sample_rate": 2000},
        "source_template": "eeg-default.toml",
        "source_template_hash": "unchanged-template-hash",
        "connection": {
            "preference": "vcp",
            "baudrate": 115200,
            "flow_control": "none",
            "read_timeout_ms": 2100,
            "write_timeout_ms": 3200,
        },
    }


def use_daemon(monkeypatch, row):
    module = importlib.import_module("app.cli.device_cmd")
    daemon = RecordingDaemon(row)
    monkeypatch.setattr(module, "DaemonClient", lambda: daemon)
    return daemon


def test_connection_show_is_read_only(monkeypatch, saved_config):
    daemon = use_daemon(monkeypatch, saved_config)
    result = CliRunner().invoke(pinnacle, ["device", "connection", "17"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["connection"] == saved_config["connection"]
    assert daemon.calls == [("GET", "/api/v1/device-configs/17", None)]


def test_connection_show_resolves_nickname_without_mutation(monkeypatch, saved_config):
    daemon = use_daemon(monkeypatch, saved_config)
    result = CliRunner().invoke(pinnacle, ["device", "connection", "left-pod"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["id"] == 17
    assert daemon.calls == [
        ("GET", "/api/v1/device-configs", None),
        ("GET", "/api/v1/device-configs/17", None),
    ]


def test_transport_update_preserves_profile_and_writes_no_template_or_acquisition_fields(
    monkeypatch,
    saved_config,
):
    daemon = use_daemon(monkeypatch, saved_config)
    result = CliRunner().invoke(
        pinnacle, ["device", "connection", "17", "--transport", "d2xx"]
    )
    assert result.exit_code == 0, result.output
    expected_connection = {**saved_config["connection"], "preference": "d2xx"}
    assert daemon.calls == [
        ("GET", "/api/v1/device-configs/17", None),
        ("PATCH", "/api/v1/device-configs/17", {"connection": expected_connection}),
    ]
    result_row = json.loads(result.output)
    assert result_row["connection"] == expected_connection
    assert result_row["parameters"] == saved_config["parameters"]
    assert result_row["source_template_hash"] == saved_config["source_template_hash"]
    assert daemon.row == saved_config


def test_profile_update_preserves_unspecified_connection_values(
    monkeypatch, saved_config
):
    daemon = use_daemon(monkeypatch, saved_config)
    result = CliRunner().invoke(
        pinnacle,
        [
            "device",
            "connection",
            "17",
            "--baudrate",
            "9600",
            "--read-timeout-ms",
            "1400",
        ],
    )
    assert result.exit_code == 0, result.output
    assert daemon.calls[-1] == (
        "PATCH",
        "/api/v1/device-configs/17",
        {
            "connection": {
                **saved_config["connection"],
                "baudrate": 9600,
                "read_timeout_ms": 1400,
            }
        },
    )


def test_legacy_empty_profile_gets_vcp_defaults_when_editing_baud(
    monkeypatch, saved_config
):
    saved_config["connection"] = {}
    daemon = use_daemon(monkeypatch, saved_config)
    result = CliRunner().invoke(
        pinnacle, ["device", "connection", "17", "--baudrate", "115200"]
    )
    assert result.exit_code == 0, result.output
    assert daemon.calls[-1][2] == {
        "connection": {
            "preference": "vcp",
            "baudrate": 115200,
            "read_timeout_ms": 5000,
            "write_timeout_ms": 5000,
        }
    }


@pytest.mark.parametrize(
    "option,value",
    [
        ("--transport", "native"),
        ("--flow-control", "xon_xoff"),
        ("--baudrate", "0"),
        ("--baudrate", "-1"),
        ("--baudrate", "fast"),
        ("--read-timeout-ms", "0"),
        ("--write-timeout-ms", "-1"),
    ],
)
def test_invalid_connection_arguments_fail_before_daemon_access(
    monkeypatch, option, value
):
    module = importlib.import_module("app.cli.device_cmd")
    monkeypatch.setattr(
        module, "DaemonClient", lambda: pytest.fail("invalid input reached daemon")
    )
    result = CliRunner().invoke(pinnacle, ["device", "connection", "17", option, value])
    assert result.exit_code == 2, result.output
    assert "Invalid value" in result.output


def isolate_doctor(monkeypatch):
    module = importlib.import_module("app.cli.doctor")
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(
        module, "collect_runtime_driver_line", lambda: "runtime driver: fake ready"
    )
    monkeypatch.setattr(module, "collect_db_lines", lambda: [])
    monkeypatch.setattr(module, "collect_migration_line", lambda: "migration: test")
    monkeypatch.setattr(module, "collect_daemon_line", lambda: "daemon: test")
    monkeypatch.setattr(module, "collect_sink_lines", lambda: [])
    return module


def guarded_driver(version_loader):
    driver = ModuleType("ftd2xx")
    driver.getLibraryVersion = version_loader

    def forbidden(*args, **kwargs):
        pytest.fail("doctor enumerated or opened an FTDI device")

    for name in (
        "createDeviceInfoList",
        "getDeviceInfoDetail",
        "listDevices",
        "open",
        "openEx",
    ):
        setattr(driver, name, forbidden)
    return driver


def test_doctor_reports_loaded_library_without_enumerating_or_opening(monkeypatch):
    isolate_doctor(monkeypatch)
    calls = []

    def version():
        calls.append("library_version")
        return 12345

    monkeypatch.setitem(sys.modules, "ftd2xx", guarded_driver(version))
    result = CliRunner().invoke(pinnacle, ["doctor"])
    assert result.exit_code == 0, result.output
    assert (
        "native D2XX: library loaded (version=12345; device access not tested)"
        in result.output
    )
    assert calls == ["library_version"]


@pytest.mark.parametrize("failure", ["missing_wrapper", "missing_dll"])
def test_doctor_native_unavailable_does_not_fail_general_diagnostics(
    monkeypatch, failure
):
    isolate_doctor(monkeypatch)
    if failure == "missing_wrapper":
        monkeypatch.setitem(sys.modules, "ftd2xx", None)
    else:

        def version():
            raise OSError("FTD2XX.dll unavailable")

        monkeypatch.setitem(sys.modules, "ftd2xx", guarded_driver(version))
    result = CliRunner().invoke(pinnacle, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "native D2XX: unavailable (" in result.output
    assert "library loaded" not in result.output
    assert "runtime driver: fake ready" in result.output
