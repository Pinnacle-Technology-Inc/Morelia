import importlib
import sys
from dataclasses import asdict, dataclass

import pytest

from app.domain.enums import DeviceType


@dataclass(frozen=True, slots=True)
class StubPort:
    device: str
    description: str
    hwid: str

    def __str__(self) -> str:
        return self.device


def _probe(*, opened=True, pinged=True, type_number=48, hardware_id="POD-ID"):
    from app.discovery.pod_scan import PodProbe

    return PodProbe(
        opened=opened,
        pinged=pinged,
        type_number=type_number,
        hardware_id=hardware_id,
    )


def test_importing_pod_scan_does_not_import_pyserial():
    sys.modules.pop("app.discovery.pod_scan", None)
    sys.modules.pop("serial", None)
    sys.modules.pop("serial.tools.list_ports", None)

    importlib.import_module("app.discovery.pod_scan")

    assert "serial" not in sys.modules
    assert "serial.tools.list_ports" not in sys.modules


def test_detect_pod_devices_emits_identified_8206hr():
    from app.discovery.pod_scan import detect_pod_devices

    ports = [StubPort("COM3", "POD 8206HR", "USB VID:PID=0403:6001 SER=A100")]

    devices = detect_pod_devices(
        port_lister=lambda: ports,
        prober=lambda port: _probe(type_number=48, hardware_id="POD-ID-7"),
    )

    assert len(devices) == 1
    device = devices[0]
    assert device.type == DeviceType.POD8206HR
    assert device.port == "COM3"
    assert device.hardware_id == "POD-ID-7"
    assert device.label == "POD 8206HR"
    assert device.availability == "available"


def test_hardware_id_falls_back_to_usb_hwid_when_device_id_absent():
    from app.discovery.pod_scan import detect_pod_devices

    ports = [StubPort("COM3", "POD 8206HR", "USB VID:PID=0403:6001 SER=A100")]

    devices = detect_pod_devices(
        port_lister=lambda: ports,
        prober=lambda port: _probe(type_number=48, hardware_id=None),
    )

    assert devices[0].hardware_id == "USB VID:PID=0403:6001 SER=A100"


def test_hardware_id_falls_back_to_dict_descriptor_when_device_id_absent():
    from app.discovery.pod_scan import detect_pod_devices

    ports = [
        {
            "device": "COM3",
            "description": "POD 8206HR",
            "hardware_id": "DICT-HW-ID",
            "vid": 0x0403,
        }
    ]

    devices = detect_pod_devices(
        port_lister=lambda: ports,
        prober=lambda port: _probe(type_number=48, hardware_id=None),
    )

    assert devices[0].port == "COM3"
    assert devices[0].hardware_id == "DICT-HW-ID"


def test_live_prober_does_not_construct_model_class_for_identity(monkeypatch):
    from app.discovery import pod_scan

    class Response:
        def __init__(self, payload):
            self.payload = payload

    class BasePod:
        def __init__(self, port, baudrate):
            self.port = port
            self.baudrate = baudrate
            self.commands: list[str] = []
            self.cleaned_up = False

        def test_connection(self):
            return True

        def write_read(self, command, timeout_sec):
            self.commands.append(command)
            if command == "TYPE":
                return Response((48,))
            if command == "ID":
                raise AssertionError("base Pod must not be used for hardware ID")
            raise AssertionError(f"unexpected command: {command}")

        def cleanup(self):
            self.cleaned_up = True

    class ModelPod8206HR:
        def __init__(self, port, preamp_gain, baudrate):
            raise AssertionError("discovery must not reopen the port via model POD")

    class DevicesModule:
        Pod = BasePod
        Pod8206HR = ModelPod8206HR

    monkeypatch.setattr(pod_scan, "_import_devices_module", lambda: DevicesModule)

    probe = pod_scan._live_prober("COM3")

    assert probe.opened is True
    assert probe.pinged is True
    assert probe.type_number == 48
    assert probe.hardware_id is None


@pytest.mark.parametrize(
    ("probe_kwargs", "expected"),
    [
        # busy / cannot open the port
        (
            {"opened": False, "pinged": False, "type_number": None, "hardware_id": None},
            [
                {
                    "type": DeviceType.UNKNOWN,
                    "port": "COM3",
                    "hardware_id": "USB VID:PID=0403:6001 SER=A100",
                    "label": "POD 8206HR",
                    "availability": "unopenable",
                }
            ],
        ),
        # opens but never pings — not a POD
        ({"opened": True, "pinged": False, "type_number": None, "hardware_id": None}, []),
        # pings as a POD model the domain does not model yet
        ({"opened": True, "pinged": True, "type_number": 999, "hardware_id": "x"}, []),
    ],
)
def test_detect_pod_devices_handles_non_emittable_ports(probe_kwargs, expected):
    from app.discovery.pod_scan import detect_pod_devices

    ports = [StubPort("COM3", "POD 8206HR", "USB VID:PID=0403:6001 SER=A100")]

    devices = detect_pod_devices(
        port_lister=lambda: ports,
        prober=lambda port: _probe(**probe_kwargs),
    )

    assert [asdict(device) for device in devices] == expected


@dataclass(frozen=True, slots=True)
class UsbPort:
    device: str
    description: str
    hwid: str
    vid: int

    def __str__(self) -> str:
        return self.device


def test_candidate_gate_skips_known_non_ftdi_vendor_without_probing():
    from app.discovery.pod_scan import detect_pod_devices

    probed: list[str] = []

    def recording_prober(port):
        probed.append(port)
        return _probe(type_number=48)

    ports = [
        UsbPort("COM3", "POD 8206HR", "USB VID:PID=0403:6001", vid=0x0403),
        UsbPort("COM4", "u-blox GNSS", "USB VID:PID=1546:01A8", vid=0x1546),
    ]

    devices = detect_pod_devices(port_lister=lambda: ports, prober=recording_prober)

    # The non-FTDI port is never opened, and only the FTDI port is emitted.
    assert probed == ["COM3"]
    assert [device.port for device in devices] == ["COM3"]


def test_candidate_gate_keeps_ports_without_usb_metadata():
    from app.discovery.pod_scan import detect_pod_devices

    devices = detect_pod_devices(
        port_lister=lambda: ["COM3"],
        prober=lambda port: _probe(type_number=48, hardware_id="ID-1"),
    )

    assert [device.port for device in devices] == ["COM3"]


def test_detect_pod_devices_treats_string_ports_as_opaque_names():
    from app.discovery.pod_scan import detect_pod_devices

    devices = detect_pod_devices(
        port_lister=lambda: ["COM3", "/dev/ttyUSB0"],
        prober=lambda port: _probe(type_number=48, hardware_id=f"ID-{port}"),
    )

    assert [device.port for device in devices] == ["COM3", "/dev/ttyUSB0"]
    assert [device.label for device in devices] == ["COM3", "/dev/ttyUSB0"]
    assert [device.hardware_id for device in devices] == ["ID-COM3", "ID-/dev/ttyUSB0"]
