"""Backend adapters reuse the original SDK models without opening physical USB."""

import multiprocessing
from contextlib import nullcontext
from queue import Queue
from types import SimpleNamespace

import pytest
from app.discovery import managed_pods
from app.discovery.managed_pods import Pod, Pod8206HR, Pod8401HR

from Morelia.Devices import Pod as LegacyPod
from Morelia.Devices import Pod8206HR as Legacy8206
from Morelia.Devices import Pod8401HR as Legacy8401
from Morelia.Devices import Preamp
from Morelia.packet import PrimaryChannelMode, SecondaryChannelMode


def _echo_from_reconstructed_source(source_type, snapshot, result_queue):
    source = source_type(**snapshot)
    command = source.obtain_write_queue().get(timeout=5)
    source.obtain_read_queue().put(("reply", command))
    source.cleanup()
    result_queue.put(
        (
            type(source).__module__,
            type(source).__name__,
            source._owns_queues,
            source.obtain_read_queue()._closed,
        )
    )


def test_probe_constructor_has_no_ipc_or_legacy_initialization(monkeypatch):
    monkeypatch.setattr(
        LegacyPod, "__init__", lambda *args, **kwargs: pytest.fail("legacy init called")
    )
    monkeypatch.setattr(
        managed_pods.multiprocessing,
        "get_context",
        lambda *args: pytest.fail("probe IPC allocated"),
    )
    source = Pod("EXACT001", use_d2xx=True, probe=True)
    try:
        assert isinstance(source.obtain_read_queue(), Queue)
        assert isinstance(source.obtain_write_queue(), Queue)
        assert source._port is None
        assert source._manager is None
        source.initialize_control_queue()
        source.register_control_queue()
    finally:
        source.cleanup()


@pytest.mark.parametrize("model", ["8206", "8401"])
def test_original_models_and_settings_reconstruct(model):
    if model == "8206":
        source = Pod8206HR(
            "EXACT001",
            10,
            use_d2xx=True,
            sample_rate=2000,
            startup_parameters={"lowpass_ch0": 100},
        )
        legacy_class = Legacy8206
    else:
        source = Pod8401HR(
            "EXACT001",
            Preamp.Preamp8406_SL,
            (PrimaryChannelMode.EEG_EMG,) * 4,
            (SecondaryChannelMode.ANALOG,) * 6,
            use_d2xx=True,
            sample_rate=2000,
            startup_parameters={"preamp_highpass_0": 2},
        )
        legacy_class = Legacy8401
    clone = None
    try:
        assert isinstance(source, legacy_class)
        snapshot = source.get_dict()
        clone = type(source)(**snapshot)
        assert clone.get_dict() == snapshot
        assert clone._port is None
        assert clone._backend_managed is True
        assert clone._startup_parameters["sample_rate"] == 2000
        assert type(clone).__name__ == "Pod" + model + "HR"
        assert type(clone).__module__ == "app.discovery.managed_pods"
        assert clone.obtain_read_queue() is source.obtain_read_queue()
        clone.cleanup()
        assert not source.obtain_read_queue()._closed
    finally:
        if clone is not None:
            clone.cleanup()
        source.cleanup()
    assert source.obtain_read_queue()._closed
    assert source.obtain_write_queue()._closed


@pytest.fixture
def fake_transport(monkeypatch):
    from app.discovery import ftdi_transport

    events = []

    class Port:
        def __init__(self, address, baudrate, **options):
            events.append(("open", address, baudrate, options))

        def deadline(self, seconds):
            return nullcontext()

        def close_serial_port(self):
            events.append(("close",))

    monkeypatch.setattr(ftdi_transport, "D2XXPortIO", Port)
    monkeypatch.setattr(ftdi_transport, "VcpPortIO", Port)

    def reply(self, cmd, payload=None, validate_checksum=True, timeout_sec=5):
        events.append(("command", cmd, payload))
        return SimpleNamespace(payload=(48,) if cmd == "TYPE" else ())

    monkeypatch.setattr(LegacyPod, "write_read", reply)
    return events


def test_open_applies_profile_and_retains_requested_settings_for_restart(
    fake_transport,
):
    source = Pod8206HR(
        "00000003",
        10,
        baudrate=115200,
        use_d2xx=True,
        sample_rate=1000,
        read_timeout_ms=2300,
        write_timeout_ms=1700,
        flow_control="none",
        probe=True,
    )
    try:
        assert fake_transport == []
        source.open_port()
        assert fake_transport == [
            (
                "open",
                "00000003",
                115200,
                {
                    "d2xx_serial_only": True,
                    "flow_control": "none",
                    "read_timeout_ms": 2300,
                    "write_timeout_ms": 1700,
                },
            ),
            ("command", "TYPE", None),
            ("command", "SET SAMPLE RATE", (1000,)),
        ]
        source.prepare_acquisition()
        assert len(fake_transport) == 3
        snapshot = source.get_dict()
        assert snapshot["startup_parameters"] == {"sample_rate": 1000}
        source.close_port()
        source.open_port()
        assert fake_transport[-2:] == [
            ("command", "TYPE", None),
            ("command", "SET SAMPLE RATE", (1000,)),
        ]
    finally:
        source.cleanup()


def test_reset_open_defers_type_and_settings(fake_transport):
    source = Pod8206HR("EXACT001", 10, use_d2xx=True, sample_rate=2000, probe=True)
    try:
        source.open_port_for_reset()
        assert len(fake_transport) == 1
        source.prepare_acquisition()
        assert fake_transport[-2:] == [
            ("command", "TYPE", None),
            ("command", "SET SAMPLE RATE", (2000,)),
        ]
    finally:
        source.cleanup()


@pytest.mark.parametrize("failed_command", [None, "TYPE", "SET SAMPLE RATE"])
@pytest.mark.parametrize("desired_rate", [None, 2000])
def test_preflight_drains_before_configuration_and_retries(
    fake_transport, monkeypatch, failed_command, desired_rate,
):
    from Morelia.Watchdog.hardwareMonitor import HardwareMonitor

    commands = []
    drained = False
    failed_once = False

    def write_packet(self, cmd, payload=None):
        nonlocal drained
        assert (cmd, payload) == ("STREAM", 0)
        commands.append(cmd)
        drained = False

    def read_packet(self, *args, **kwargs):
        nonlocal drained
        commands.append("drain")
        drained = True
        raise TimeoutError("device is quiet")

    def reply(self, cmd, payload=None, *args, **kwargs):
        nonlocal failed_once
        commands.append(cmd)
        if not drained:
            raise TimeoutError("configuration attempted before reset and drain")
        if cmd == failed_command and not failed_once:
            failed_once = True
            raise TimeoutError("first configuration response missing")
        return SimpleNamespace(payload=(48,) if cmd == "TYPE" else (2000,))

    monkeypatch.setattr(LegacyPod, "write_packet", write_packet)
    monkeypatch.setattr(LegacyPod, "read_pod_packet", read_packet)
    monkeypatch.setattr(LegacyPod, "write_read", reply)
    source = Pod8206HR("EXACT001", 10, use_d2xx=True, sample_rate=2000, probe=True)
    try:
        result = HardwareMonitor(3).preflight_device(
            source, desired_sample_rate=desired_rate,
        )
        assert result["ok"], result
        assert result["attempts_used"] == (2 if failed_command else 1)
        assert commands[:3] == ["STREAM", "drain", "TYPE"]
        assert commands.count("STREAM") == result["attempts_used"]
        assert commands[-1] == "GET SAMPLE RATE"
        assert source._port is None
        assert fake_transport[-1] == ("close",)
    finally:
        source.cleanup()


def test_preflight_does_not_configure_when_reset_fails(fake_transport, monkeypatch):
    from Morelia.Watchdog.hardwareMonitor import HardwareMonitor

    def write_packet(self, cmd, payload=None):
        raise OSError("device did not accept STREAM 0")

    monkeypatch.setattr(LegacyPod, "write_packet", write_packet)
    source = Pod8206HR("EXACT001", 10, use_d2xx=True, sample_rate=2000, probe=True)
    try:
        result = HardwareMonitor(3).preflight_device(source, attempts=2)
        assert not result["ok"]
        assert result["attempts_used"] == 2
        assert "device reset failed" in result["error"]
        assert not any(event[0] == "command" for event in fake_transport)
        assert source._port is None
    finally:
        source.cleanup()


def test_wrong_model_closes_handle_without_applying_settings(
    fake_transport, monkeypatch
):
    monkeypatch.setattr(
        LegacyPod,
        "write_read",
        lambda *_args, **_kwargs: SimpleNamespace(payload=(49,)),
    )
    source = Pod8206HR("EXACT001", 10, use_d2xx=True, sample_rate=2000, probe=True)
    with pytest.raises(ValueError, match="TYPE"):
        source.open_port()
    assert source._port is None
    assert fake_transport[-1] == ("close",)


def test_swallowed_sdk_setter_failure_prevents_success(fake_transport, monkeypatch):
    def reply(self, cmd, payload=None, *args, **kwargs):
        if cmd == "TYPE":
            return SimpleNamespace(payload=(49,))
        raise OSError("native write failed")

    monkeypatch.setattr(LegacyPod, "write_read", reply)
    source = Pod8401HR(
        "EXACT001",
        Preamp.Preamp8406_SL,
        (PrimaryChannelMode.EEG_EMG,) * 4,
        (SecondaryChannelMode.ANALOG,) * 6,
        use_d2xx=True,
        probe=True,
        startup_parameters={"preamp_highpass_0": 2},
    )
    with pytest.raises(RuntimeError, match="Failed to configure"):
        source.open_port()
    assert source._port is None
    assert fake_transport[-1] == ("close",)


def test_real_spawn_reconstruction_shares_parent_queues():
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    source = Pod8206HR("EXACT001", 10, use_d2xx=True, sample_rate=2000)
    worker = context.Process(
        target=_echo_from_reconstructed_source,
        args=(type(source), source.get_dict(), result_queue),
    )
    try:
        worker.start()
        source.obtain_write_queue().put(b"parent command")
        assert source.obtain_read_queue().get(timeout=10) == (
            "reply",
            b"parent command",
        )
        assert result_queue.get(timeout=10) == (
            "app.discovery.managed_pods",
            "Pod8206HR",
            False,
            False,
        )
        worker.join(timeout=10)
        assert worker.exitcode == 0
        assert not source.obtain_read_queue()._closed
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=5)
        source.cleanup()
        result_queue.close()
        result_queue.join_thread()


def test_failed_close_retains_handle_and_cleanup_closes_owned_queues_once(monkeypatch):
    source = Pod("EXACT001", use_d2xx=True)
    close_attempts = []
    queue_closes = []

    def close_port():
        close_attempts.append(True)
        if len(close_attempts) == 1:
            raise OSError("close failed")

    port = SimpleNamespace(close_serial_port=close_port)
    source._port = port
    source._prepared = True
    for index, owned_queue in enumerate(
        (source.obtain_write_queue(), source.obtain_read_queue())
    ):
        original_close = owned_queue.close

        def close_queue(index=index, original_close=original_close):
            queue_closes.append(index)
            original_close()

        monkeypatch.setattr(owned_queue, "close", close_queue)

    with pytest.raises(OSError, match="close failed"):
        source.cleanup()
    assert source._port is port
    assert source._prepared is False
    assert queue_closes == []

    source.cleanup()
    source.cleanup()
    assert source._port is None
    assert len(close_attempts) == 2
    assert queue_closes == [0, 1]


def test_legacy_read_retry_cannot_turn_driver_error_into_type_timeout(monkeypatch):
    source = Pod("EXACT001", use_d2xx=True, probe=True)
    source._port = SimpleNamespace(
        deadline=lambda _seconds: nullcontext(), close_serial_port=lambda: None
    )
    failure = OSError("native read failed")

    def read_error(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(LegacyPod, "read_pod_packet", read_error)
    monkeypatch.setattr(LegacyPod, "flush_port", lambda *_args: None)
    monkeypatch.setattr(LegacyPod, "write_packet", lambda *_args: None)
    try:
        with pytest.raises(OSError, match="native read failed") as raised:
            source.write_read("TYPE", timeout_sec=0.01)
        assert raised.value is failure
        assert isinstance(raised.value.__cause__, TimeoutError)
        assert source._last_command_failure is failure
    finally:
        source.cleanup()
