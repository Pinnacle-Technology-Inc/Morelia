from app.database import db
from app.discovery.pod_scan import DiscoveredDevice
from app.domain.enums import DeviceType
from app.models.device_config import DeviceConfig
from app.repositories.sessions import SessionRepository
from app.services.discovery import DeviceDiscoveryService, FakeDiscoveryProvider

API = "/api/v1/device-configs"


def test_device_config_crud_routes_create_show_list_edit_and_delete(client, app):
    created = client.post(
        API,
        json={
            "type": "pod8206hr",
            "hardware_id": "001",
            "port": "COM3",
            "parameters": {"preamp_gain": "10"},
            "nickname": "Left POD",
        },
    )

    assert created.status_code == 201
    body = created.get_json()
    assert body["id"]
    assert body["type"] == "pod8206hr"
    assert body["hardware_id"] == "001"
    assert body["parameters"] == {"preamp_gain": 10}
    assert len(body["color"]) == 7
    assert body["color"].startswith("#")
    assert body["claim_state"] == "free"
    assert body["source_template_hash"] is None

    shown = client.get(f"{API}/{body['id']}")
    assert shown.status_code == 200
    assert shown.get_json()["hardware_id"] == "001"

    listed = client.get(API)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.get_json()] == [body["id"]]

    edited = client.patch(
        f"{API}/{body['id']}",
        json={"parameters": {"preamp_gain": 100}},
    )
    assert edited.status_code == 200
    assert edited.get_json()["parameters"] == {"preamp_gain": 100}

    deleted = client.delete(f"{API}/{body['id']}")
    assert deleted.status_code == 200
    assert deleted.get_json() == {"deleted_id": body["id"]}
    with app.app_context():
        assert db.session.get(DeviceConfig, body["id"]) is None


def test_create_from_template_tracks_template_id_and_edit_severs_by_default(client):
    template = client.post(
        "/api/v1/device-templates",
        json={
            "name": "pod-high",
            "type": "pod8206hr",
            "parameters": {"preamp_gain": 10},
        },
    ).get_json()
    created = client.post(
        f"{API}/from-template",
        json={
            "template_name": "pod-high",
            "hardware_id": "002",
            "port": "COM4",
        },
    ).get_json()

    assert created["source_template"] == "device-templates/pod-high.toml"
    assert created["source_template_hash"] == template["content_hash"]

    edited = client.patch(
        f"{API}/{created['id']}",
        json={"parameters": {"preamp_gain": 100}},
    )

    assert edited.status_code == 200
    body = edited.get_json()
    assert body["source_template"] is None
    assert body["source_template_hash"] is None
    assert body["source_template_history"] == "device-templates/pod-high.toml"

    unchanged_template = client.get("/api/v1/device-templates/pod-high").get_json()
    assert unchanged_template["content"]["parameters"] == {"preamp_gain": 10}


def test_name_device_config_updates_alias_by_hardware_identity(client):
    created = client.post(
        API,
        json={
            "type": "pod8206hr",
            "hardware_id": "003",
            "port": "COM4",
            "parameters": {"preamp_gain": 10},
        },
    ).get_json()

    renamed = client.post(
        f"{API}/name",
        json={"type": "pod8206hr", "hardware_id": "003", "nickname": "Tom"},
    )

    assert renamed.status_code == 200
    assert renamed.get_json()["id"] == created["id"]
    assert renamed.get_json()["nickname"] == "Tom"


def test_device_name_can_be_registered_before_configuration(client):
    registered = client.post(
        "/api/v1/device-registrations",
        json={"type": "pod8206hr", "hardware_id": "004", "nickname": "pre-pod"},
    )

    assert registered.status_code == 200
    body = registered.get_json()
    assert body["type"] == "pod8206hr"
    assert body["hardware_id"] == "004"
    assert body["nickname"] == "pre-pod"
    assert body["device_config_id"] is None

    duplicate_name = client.post(
        "/api/v1/device-registrations",
        json={"type": "pod8206hr", "hardware_id": "005", "nickname": "pre-pod"},
    )
    assert duplicate_name.status_code == 409
    assert duplicate_name.get_json()["code"] == "device_nickname_exists"


def test_config_creation_binds_pre_registered_name_to_device_config(client):
    registered = client.post(
        "/api/v1/device-registrations",
        json={"type": "pod8206hr", "hardware_id": "006", "nickname": "bound-pod"},
    ).get_json()

    created = client.post(
        API,
        json={
            "type": "pod8206hr",
            "hardware_id": "006",
            "port": "COM3",
            "parameters": {"preamp_gain": 10},
        },
    )

    assert created.status_code == 201
    config = created.get_json()
    assert config["nickname"] == "bound-pod"

    registrations = client.get("/api/v1/device-registrations").get_json()
    bound = next(row for row in registrations if row["id"] == registered["id"])
    assert bound["device_config_id"] == config["id"]


def test_edit_with_writeback_updates_linked_template_and_keeps_provenance(client):
    template = client.post(
        "/api/v1/device-templates",
        json={
            "name": "pod-high",
            "type": "pod8206hr",
            "parameters": {"preamp_gain": 10},
        },
    ).get_json()
    created = client.post(
        f"{API}/from-template",
        json={
            "template_name": "pod-high",
            "hardware_id": "007",
            "port": "COM5",
        },
    ).get_json()

    edited = client.patch(
        f"{API}/{created['id']}",
        json={
            "parameters": {"preamp_gain": 100},
            "update_source_template": True,
        },
    )

    assert edited.status_code == 200
    body = edited.get_json()
    assert body["source_template"] == "device-templates/pod-high.toml"
    assert body["source_template_hash"] != template["content_hash"]
    updated_template = client.get("/api/v1/device-templates/pod-high").get_json()
    assert updated_template["content"]["parameters"] == {"preamp_gain": 100}


def test_device_pool_lists_configs_and_unconfigured_latest_scan_rows(client, app):
    with app.app_context():
        config = client.post(
            API,
            json={
                "type": "pod8206hr",
                "hardware_id": "008",
                "port": "COM6",
                "parameters": {"preamp_gain": 10},
            },
        ).get_json()
        session = SessionRepository().create({"name": "Run A", "device_flows": []})
        session_id = session.id
        from app.services import device_configs

        device_configs.claim(config["id"], session_id)

    app.extensions["device_discovery_service"] = DeviceDiscoveryService(
        FakeDiscoveryProvider(
            [
                DiscoveredDevice(
                    type=DeviceType.POD8206HR,
                    port="COM6",
                    hardware_id="008",
                    label="Configured POD",
                    availability="available",
                ),
                DiscoveredDevice(
                    type=DeviceType.POD8206HR,
                    port="COM7",
                    hardware_id="009",
                    label="Fresh POD",
                    availability="available",
                ),
            ]
        )
    )

    response = client.get("/api/v1/devices/pool")

    assert response.status_code == 200
    assert response.get_json()["devices"] == [
        {
            "id": config["id"],
            "type": "pod8206hr",
            "port": "COM6",
                "hardware_id": "008",
                "color": config["color"],
                "availability": "available",
            "status": "claimed",
            "owner": session_id,
            "nickname": None,
            "label": "Configured POD",
        },
        {
            "id": None,
            "type": "pod8206hr",
            "port": "COM7",
                "hardware_id": "009",
                "color": None,
                "availability": "available",
            "status": "unconfigured",
            "owner": None,
            "nickname": None,
            "label": "Fresh POD",
        },
    ]
