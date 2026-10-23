"""Independent oracle: dashboard transport must work with unchanged SDK Devices.

Real model initialization, model serialization, packet codecs, and Windows-style
spawn queues run here. Physical USB and SDK queue-server creation are forbidden.
The original SDK constructor is the negative control for the queue-server guard.
"""

from __future__ import annotations

import ast
import importlib
import multiprocessing as mp
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


def _models():
    return importlib.import_module("app.discovery.managed_pods")


def _kwargs():
    return {
        "port": "AB0MZ1AZ",
        "preamp_gain": 10,
        "baudrate": 115200,
        "sample_rate": 2000,
        "device_name": "Boundary EEG",
        "use_d2xx": True,
        "d2xx_serial_only": True,
        "flow_control": "rts_cts",
        "read_timeout_ms": 1700,
        "write_timeout_ms": 2300,
        "startup_parameters": {"lowpass_ch0": 100},
    }


def _close_queues(source):
    source.cleanup()
    for queue in (source.obtain_write_queue(), source.obtain_read_queue()):
        # Cleanup may already close owner queues. Never join a feeder with
        # unread messages; these tests fully drain all roundtrips first.
        queue.close()
        queue.join_thread()


def _spawn_echo(source_class, source_dict, result):
    """Exercise the SDK's exact reconstruction contract in a fresh process."""
    try:
        source = source_class(**source_dict)
        command = source.obtain_write_queue().get(timeout=8)
        expected = source.get_pod_packet("PING")
        if command != expected:
            raise AssertionError("Worker received another device's command")
        # PING has no arguments or response payload: the SDK's encoded packet
        # is also its protocol-valid echo response. No USB interaction needed.
        source.obtain_read_queue().put(command)
        result.put(
            {
                "name": type(source).__name__,
                "module": type(source).__module__,
                "port": source.port,
                "baudrate": source.baudrate,
                "sample_rate": source.sample_rate,
                "closed": source._port is None,
            }
        )
        # Worker cleanup must not invalidate the parent's channel ownership.
        source.cleanup()
    except BaseException as exc:
        result.put({"error": f"{type(exc).__name__}: {exc}"})
        raise


def test_devices_source_has_no_backend_import_dependency():
    import Morelia.Devices

    root = Path(Morelia.Devices.__file__).parent
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            modules = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else (
                    [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else []
                )
            )
            assert not any(
                name == "app" or name.startswith("app.") for name in modules
            ), path


@pytest.mark.parametrize("use_d2xx", [False, True])
def test_managed_models_do_not_replace_sdk_namespace_or_start_queue_server(
    monkeypatch, use_d2xx
):
    import Morelia.Devices as sdk
    from Morelia.Devices.BasicPodProtocol import Pod as OriginalPod
    from Morelia.Devices.SerialPorts.queue_manager import PacketManager

    originals = (
        sdk.Pod,
        sdk.Pod8206HR,
        sdk.Pod8401HR,
        OriginalPod.open_port,
        OriginalPod.write_read,
        PacketManager.initialize_control_queue,
    )
    queue_server_calls = []

    def forbidden_server(_self):
        queue_server_calls.append(True)
        raise AssertionError("SDK queue-server construction is forbidden")

    with monkeypatch.context() as guard:
        guard.setattr(PacketManager, "initialize_control_queue", forbidden_server)
        models = _models()
        kwargs = _kwargs()
        if not use_d2xx:
            kwargs.update(
                port="COM9", use_d2xx=False, d2xx_serial_only=False, flow_control="none"
            )
        source = models.Pod8206HR(**kwargs)
        try:
            assert source._port is None
            assert isinstance(source, sdk.Pod8206HR)
            assert type(source).__name__ == "Pod8206HR"
            assert type(source).__module__ == "app.discovery.managed_pods"
            assert (
                sdk.Pod,
                sdk.Pod8206HR,
                sdk.Pod8401HR,
                OriginalPod.open_port,
                OriginalPod.write_read,
            ) == originals[:5]
            assert not queue_server_calls
            assert PacketManager.initialize_control_queue is forbidden_server
        finally:
            _close_queues(source)
    assert PacketManager.initialize_control_queue is originals[5]


def test_original_constructor_negative_control_hits_queue_server_guard(monkeypatch):
    import Morelia.Devices as sdk
    import Morelia.Devices.SerialPorts as serial_ports
    from Morelia.Devices.SerialPorts.queue_manager import PacketManager

    def forbidden_server(_self):
        raise AssertionError("SDK queue-server construction is forbidden")

    # Native construction defers USB opening; dependency availability is the
    # only prerequisite before the original constructor creates its server.
    monkeypatch.setattr(serial_ports, "D2XX_AVAILABLE", True)
    monkeypatch.setattr(PacketManager, "initialize_control_queue", forbidden_server)
    with pytest.raises(AssertionError, match="queue-server construction"):
        sdk.Pod8206HR("AB0MZ1AZ", 10, use_d2xx=True, sample_rate=2000)


@pytest.mark.parametrize("model_name", ["Pod8206HR", "Pod8401HR"])
def test_get_dict_preserves_reconstruction_type_settings_and_queue_identity(model_name):
    from Morelia.Devices import Preamp
    from Morelia.packet import PrimaryChannelMode, SecondaryChannelMode

    models = _models()
    kwargs = _kwargs()
    if model_name == "Pod8401HR":
        kwargs.update(
            preamp=Preamp.Preamp8407_SE4,
            primary_channel_modes=(PrimaryChannelMode.EEG_EMG,) * 4,
            secondary_channel_modes=(SecondaryChannelMode.ANALOG,) * 2,
            preamp_gain=(10,) * 4,
        )
    source = getattr(models, model_name)(**kwargs)
    rebuilt = None
    try:
        snapshot = source.get_dict()
        expected = {
            **kwargs,
            "startup_parameters": {
                **kwargs["startup_parameters"],
                "sample_rate": kwargs["sample_rate"],
            },
        }
        for name, value in expected.items():
            assert snapshot[name] == value, name
        rebuilt = type(source)(**snapshot)
        assert type(rebuilt) is type(source)
        assert rebuilt.obtain_write_queue() is source.obtain_write_queue()
        assert rebuilt.obtain_read_queue() is source.obtain_read_queue()
        assert rebuilt._port is None
    finally:
        if rebuilt is not None:
            rebuilt.cleanup()
        _close_queues(source)


def test_real_spawn_preserves_monitor_roundtrip_and_channel_reuse():
    # pytest importlib mode uses a non-importable hyphenated test package on
    # Windows. Publish this worker under a stable, importable test-module name.
    module_name = "test_backend_transport_boundary"
    test_dir = str(Path(__file__).parent)
    if test_dir not in sys.path:
        sys.path.insert(0, test_dir)
    sys.modules[module_name] = sys.modules[__name__]
    _spawn_echo.__module__ = module_name
    context = mp.get_context("spawn")
    result = context.Queue()
    source = _models().Pod8206HR(**_kwargs())
    processes = []
    try:
        # A second worker reconstructs after the first exits, like recovery.
        for _attempt in range(2):
            process = context.Process(
                target=_spawn_echo,
                args=(type(source), source.get_dict(), result),
            )
            processes.append(process)
            process.start()
            response = source.write_read("PING", timeout_sec=10)
            assert response.command_number == source._commands.command_number_from_name(
                "PING"
            )
            report = result.get(timeout=10)
            assert report == {
                "name": "Pod8206HR",
                "module": "app.discovery.managed_pods",
                "port": "AB0MZ1AZ",
                "baudrate": 115200,
                "sample_rate": 2000,
                "closed": True,
            }
            process.join(10)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5)
        _close_queues(source)
        result.close()
        result.join_thread()


def test_probe_uses_no_queue_server_or_spawn_context(monkeypatch):
    from Morelia.Devices.SerialPorts.queue_manager import PacketManager

    def forbidden(*args, **kwargs):
        raise AssertionError("Discovery must not create queue servers or spawn queues")

    monkeypatch.setattr(PacketManager, "initialize_control_queue", forbidden)
    monkeypatch.setattr(mp, "get_context", forbidden)
    probe = _models().Pod("AB0MZ1AZ", use_d2xx=True, probe=True)
    try:
        assert probe._port is None
        assert probe.get_dict()["port"] == "AB0MZ1AZ"
        probe.obtain_write_queue().put(b"probe-local")
        assert probe.obtain_write_queue().get_nowait() == b"probe-local"
    finally:
        probe.cleanup()


class _UsbHandle:
    """Only USB is mocked; the backend framing and SDK codecs remain real."""

    def __init__(self, serial):
        self.serial = serial
        self.calls = []
        self.pending = b""

    def getDeviceInfo(self):
        return {"serial": self.serial.encode()}

    def setBaudRate(self, *args):
        self.calls.append(("baud", args))

    def setDataCharacteristics(self, *args):
        self.calls.append(("data", args))

    def setFlowControl(self, *args):
        self.calls.append(("flow", args))

    def setTimeouts(self, *args):
        self.calls.append(("timeouts", args))

    def purge(self, *args):
        self.calls.append(("purge", args))

    def write(self, message):
        assert isinstance(message, bytes)
        self.calls.append(("write", message))
        self.pending += message
        return len(message)

    def read(self, size):
        data, self.pending = self.pending[:size], self.pending[size:]
        return data

    def close(self):
        self.calls.append(("close", ()))


def _mock_usb(monkeypatch, handle, *, inventory_serial="AB0MZ1AZ"):
    transport = importlib.import_module("app.discovery.ftdi_transport")
    opens = []

    def open_exact(serial):
        opens.append(serial)
        return handle

    driver = SimpleNamespace(
        createDeviceInfoList=lambda: 1,
        getDeviceInfoDetail=lambda index, update: {"serial": inventory_serial.encode()},
    )
    monkeypatch.setattr(transport, "ftd", driver)
    monkeypatch.setattr(transport, "_open_native_serial", open_exact)
    return transport, opens


def test_wrong_opened_serial_is_closed_before_configuration_or_write(monkeypatch):
    handle = _UsbHandle("ANOTHER-POD")
    _transport, opens = _mock_usb(monkeypatch, handle)
    source = _models().Pod8206HR(**_kwargs())
    try:
        with pytest.raises(ValueError, match="identity"):
            source.open_port()
        assert opens == ["AB0MZ1AZ"]
        assert handle.calls == [("close", ())]
        assert source._port is None
    finally:
        _close_queues(source)


def test_numeric_native_selector_never_falls_back_to_device_index(monkeypatch):
    handle = _UsbHandle("AB0MZ1AZ")
    transport, opens = _mock_usb(monkeypatch, handle)
    with pytest.raises(ValueError, match="identity"):
        transport.D2XXPortIO("0")
    assert opens == ["0"]
    assert handle.calls == [("close", ())]


def test_real_sdk_packet_path_preserves_bytes_and_native_settings(monkeypatch):
    handle = _UsbHandle("AB0MZ1AZ")
    _transport, opens = _mock_usb(monkeypatch, handle)
    source = _models().Pod8206HR(**_kwargs())
    try:
        source.open_port(configure=False)
        assert opens == ["AB0MZ1AZ"]
        assert handle.calls[:5] == [
            ("baud", (115200,)),
            ("data", (8, 0, 0)),
            ("flow", (256, 0x11, 0x13)),
            ("timeouts", (1700, 2300)),
            ("purge", (3,)),
        ]
        response = source.write_read("PING", timeout_sec=0.25)
        assert response.command_number == source._commands.command_number_from_name(
            "PING"
        )
        assert ("write", source.get_pod_packet("PING")) in handle.calls
    finally:
        _close_queues(source)
    assert handle.calls[-1] == ("close", ())


@pytest.mark.parametrize("partial_next_packet", [False, True])
def test_unchanged_sdk_get_data_decodes_native_sample_and_stops_cleanly(
    monkeypatch, partial_next_packet
):
    from Morelia.packet.data import DataPacket8206HR
    from Morelia.signal import DigitalSignal
    from Morelia.Stream.source import get_data
    from tests.mocks.packet.data.MockDataPacket8206HR import MockDataPacket8206HR
    from tests.mocks.packet.MockControlPacket import MockControlPacket

    fixture = MockDataPacket8206HR(
        ch0=4,
        ch1=200,
        ch2=97,
        ttl1=1,
        ttl3=1,
        packet_number=245,
    ).to_bytes()
    ping_written = threading.Event()
    stop = threading.Event()
    source_errors, sink_errors = [], []

    def on_source_error(event):
        source_errors.append(event)
        stop.set()

    class StreamingUsb(_UsbHandle):
        def write(self, message):
            assert isinstance(message, bytes)
            self.calls.append(("write", message))
            command = int(message[1:5], 16)
            payload = message[5:-3]
            if command == 8:  # TYPE 8206HR, from the existing SDK command table.
                self.pending += MockControlPacket(8, b"30").to_bytes()
            elif command in (
                101,
                103,
            ):  # SET SAMPLE RATE / SET LOWPASS acknowledgments.
                self.pending += MockControlPacket(command).to_bytes()
            elif command == 6 and payload == b"01":
                self.pending += fixture + (b"\x02" if partial_next_packet else b"")
            elif command == 6 and payload == b"00":
                self.pending += MockControlPacket(6, b"00").to_bytes()
            elif command == 2:  # Actual SDK background writer drains the parent queue.
                ping_written.set()
            else:
                raise AssertionError(
                    f"Unexpected device command {command}: {payload!r}"
                )
            return len(message)

        def read(self, size):
            if not self.pending:
                time.sleep(0.002)
            return super().read(size)

    class MemorySink:
        def __init__(self):
            self.samples = []
            self.closed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.closed = True

        def flush(self, timestamp, packet):
            self.samples.append((timestamp, packet))
            ping_written.wait(0.5)
            if not partial_next_packet:
                stop.set()

    handle = StreamingUsb("AB0MZ1AZ")
    _mock_usb(monkeypatch, handle)
    source = _models().Pod8206HR(**_kwargs())
    sink = MemorySink()
    # Bound a broken streaming loop independently of its own duration handling.
    guard = threading.Timer(3, stop.set)
    guard.start()
    started = time.monotonic()
    try:
        source.obtain_write_queue().put(source.get_pod_packet("PING"))
        get_data(
            1,
            stop,
            source,
            [sink],
            on_source_error=on_source_error,
            on_sink_error=sink_errors.append,
        )
        assert time.monotonic() - started < 3
        assert stop.is_set() and ping_written.is_set()
        assert sink.closed and source._port is None
        assert not sink_errors
        if partial_next_packet:
            assert len(source_errors) == 1
            assert source_errors[0]["exception_type"] == "TimeoutError"
        else:
            assert not source_errors
        assert len(sink.samples) == 1
        timestamp, packet = sink.samples[0]
        assert timestamp > 0
        assert isinstance(packet, DataPacket8206HR)
        assert packet._raw_packet == fixture
        assert (packet.ch0, packet.ch1, packet.ch2) == pytest.approx(
            tuple(
                ((adc / 65535 * 4.096) - 2.048) / (10 * 50.2918) * 1e6
                for adc in (4, 200, 97)
            )
        )
        assert (packet.ttl1, packet.ttl2, packet.ttl3, packet.ttl4) == (
            DigitalSignal.HIGH,
            DigitalSignal.LOW,
            DigitalSignal.HIGH,
            DigitalSignal.LOW,
        )
        writes = [value for name, value in handle.calls if name == "write"]
        assert writes[:3] == [
            source.get_pod_packet("TYPE"),
            source.get_pod_packet("SET LOWPASS", (0, 100)),
            source.get_pod_packet("SET SAMPLE RATE", (2000,)),
        ]
        assert source.get_pod_packet("STREAM", 1) in writes[3:]
        assert writes[-1] == source.get_pod_packet("STREAM", 0)
        assert handle.calls[-1] == ("close", ())
    finally:
        guard.cancel()
        stop.set()
        _close_queues(source)
