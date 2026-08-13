from datetime import UTC

from app import create_app
from app.discovery.pod_scan import DiscoveredDevice, PodProbe
from app.domain.enums import DeviceType
from app.services.discovery import (
    FakeDiscoveryProvider,
    SerialPodProvider,
)


def test_get_devices_returns_fake_scan_result_in_testing(client):
    response = client.get("/api/v1/devices/")

    assert response.status_code == 200
    body = response.get_json()
    assert body["scan_id"]
    assert body["scanned_at"].endswith("+00:00")
    assert body["devices"] == [
        {
            "type": "pod8206hr",
            "port": "FAKE-POD-8206HR",
            "hardware_id": "99999999",
            "label": "Fake POD 8206HR",
            "availability": "available",
        }
    ]


def test_device_discovery_service_scan_metadata_is_utc(app):
    service = app.extensions["device_discovery_service"]

    result = service.scan()

    assert result.scan_id
    assert result.scanned_at.tzinfo is UTC
    assert result.devices[0].type is DeviceType.POD8206HR


def test_register_routes_selects_fake_provider_under_testing(app):
    assert isinstance(app.extensions["device_discovery_provider"], FakeDiscoveryProvider)


def test_register_routes_selects_serial_provider_outside_testing():
    app = create_app(
        "development",
        config_overrides={
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "STARTUP_RECONCILIATION_ENABLED": False,
        },
    )

    assert app.testing is False
    assert isinstance(app.extensions["device_discovery_provider"], SerialPodProvider)


def test_serial_provider_passes_injected_collaborators_to_pod_scan():
    provider = SerialPodProvider(
        port_lister=lambda: [
            type(
                "PortInfo",
                (),
                {
                    "device": "COM9",
                    "description": "POD 8206HR",
                    "hwid": "USB VID:PID=0403:6001 SER=SERIAL9",
                },
            )()
        ],
        prober=lambda port: PodProbe(
            opened=True,
            pinged=True,
            type_number=48,
            hardware_id="POD-ID-9",
        ),
    )

    devices = provider.scan()

    assert devices == [
        DiscoveredDevice(
            type=DeviceType.POD8206HR,
            port="COM9",
            hardware_id="POD-ID-9",
            label="POD 8206HR",
            availability="available",
        )
    ]
