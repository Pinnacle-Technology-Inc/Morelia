"""Contract tests for the immutable runtime manifest v2 (packet 06).

These prove that a Manifest (and its nested SinkConfig / DeviceFlow value
objects) serializes and round-trips cleanly, is immutable after construction,
rejects invalid/secret/unknown configurations, produces a stable content hash
for equal inputs (with sink order significant but dict order not), reads and
translates persisted v1 documents to a single canonical file sink, and carries
a nullable durable session identity.
"""

import pytest

from app.domain.enums import PolicyMode, SinkType
from app.runtime_host.manifest import (
    MANIFEST_SCHEMA_VERSION,
    DeviceFlow,
    Manifest,
    SinkConfig,
)

_V1_SCHEMA_VERSION = "1"


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


def _csv_sink(device_id: str, location: str) -> SinkConfig:
    return SinkConfig(
        sink_id=f"{device_id}:csv",
        name="csv",
        type=SinkType.CSV,
        parameters={"file_path": location},
    )


def _flow(device_id: str, location: str | None = None) -> DeviceFlow:
    loc = location or f"/data/{device_id}.csv"
    return DeviceFlow(
        device_id=device_id,
        name=f"device-{device_id}",
        nickname=None,
        hardware_id=f"hw-{device_id}",
        port="usb-1",
        parameters={"sample_rate": 250},
        sinks=(_csv_sink(device_id, loc),),
    )


def _manifest(session_id: int | None = None) -> Manifest:
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        dataflow_id="df-1",
        policy=PolicyMode.RECOMMEND,
        device_flows=(_flow("dev-a"), _flow("dev-b")),
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# round-trip
# ---------------------------------------------------------------------------


def test_manifest_round_trips_through_wire_form():
    m = _manifest()
    assert Manifest.from_dict(m.to_dict()) == m


def test_manifest_round_trips_with_session_id():
    m = _manifest(session_id=42)
    round_tripped = Manifest.from_dict(m.to_dict())
    assert round_tripped == m
    assert round_tripped.session_id == 42


def test_device_flow_round_trips_through_wire_form():
    df = _flow("dev-a")
    assert DeviceFlow.from_dict(df.to_dict()) == df


def test_sink_config_round_trips_through_wire_form():
    s = _csv_sink("dev-a", "/data/dev-a.csv")
    assert SinkConfig.from_dict(s.to_dict()) == s


def test_device_flow_round_trips_with_nickname():
    df = DeviceFlow(
        device_id="dev-a",
        name="device-a",
        nickname="my-sensor",
        hardware_id="hw-a",
        port="usb-1",
        parameters={},
        sinks=(_csv_sink("dev-a", "/data/dev-a.csv"),),
    )
    assert DeviceFlow.from_dict(df.to_dict()) == df


def test_device_flow_nickname_defaults_to_none_when_absent():
    wire = _flow("dev-a").to_dict()
    del wire["nickname"]
    assert DeviceFlow.from_dict(wire).nickname is None


def test_wire_form_is_pure_v2_without_v1_sink_fields():
    wire = _flow("dev-a").to_dict()
    assert "sinks" in wire
    assert "sink_type" not in wire
    assert "sink_location" not in wire


def test_schema_version_is_two():
    assert MANIFEST_SCHEMA_VERSION == "2"
    assert _manifest().to_dict()["schema_version"] == "2"


# ---------------------------------------------------------------------------
# multi-sink device flows
# ---------------------------------------------------------------------------


def test_device_flow_supports_multiple_sinks():
    df = DeviceFlow(
        device_id="dev-a",
        name="device-a",
        nickname=None,
        hardware_id="hw-a",
        port="usb-1",
        parameters={},
        sinks=(
            _csv_sink("dev-a", "/data/dev-a.csv"),
            SinkConfig(
                sink_id="dev-a:quest-live",
                name="quest-live",
                type=SinkType.QUEST,
                parameters={"host": "localhost", "port": 9009, "measurement": "exp_a"},
            ),
        ),
    )
    assert len(df.sinks) == 2
    assert DeviceFlow.from_dict(df.to_dict()) == df


def test_device_flow_requires_at_least_one_sink():
    with pytest.raises(ValueError, match="at least one sink"):
        DeviceFlow(
            device_id="dev-a",
            name="device-a",
            nickname=None,
            hardware_id="hw-a",
            port="usb-1",
            parameters={},
            sinks=(),
        )


def test_device_flow_rejects_duplicate_sink_ids():
    with pytest.raises(ValueError, match="duplicate sink_id"):
        DeviceFlow(
            device_id="dev-a",
            name="device-a",
            nickname=None,
            hardware_id="hw-a",
            port="usb-1",
            parameters={},
            sinks=(
                SinkConfig(sink_id="s1", name="a", type=SinkType.CSV, parameters={"file_path": "/x"}),
                SinkConfig(sink_id="s1", name="b", type=SinkType.CSV, parameters={"file_path": "/y"}),
            ),
        )


def test_device_flow_rejects_duplicate_sink_names():
    with pytest.raises(ValueError, match="duplicate sink name"):
        DeviceFlow(
            device_id="dev-a",
            name="device-a",
            nickname=None,
            hardware_id="hw-a",
            port="usb-1",
            parameters={},
            sinks=(
                SinkConfig(sink_id="s1", name="same", type=SinkType.CSV, parameters={"file_path": "/x"}),
                SinkConfig(sink_id="s2", name="same", type=SinkType.CSV, parameters={"file_path": "/y"}),
            ),
        )


# ---------------------------------------------------------------------------
# immutability
# ---------------------------------------------------------------------------


def test_manifest_is_frozen():
    m = _manifest()
    with pytest.raises(AttributeError):
        m.dataflow_id = "df-other"  # type: ignore[misc]


def test_device_flow_is_frozen():
    df = _flow("dev-a")
    with pytest.raises(AttributeError):
        df.device_id = "dev-b"  # type: ignore[misc]


def test_sink_config_is_frozen():
    s = _csv_sink("dev-a", "/data/dev-a.csv")
    with pytest.raises(AttributeError):
        s.sink_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# reject unknown / mixed fields (strict from_dict)
# ---------------------------------------------------------------------------


def test_manifest_rejects_unknown_fields():
    wire = _manifest().to_dict()
    wire["unexpected"] = "smuggled"
    with pytest.raises(ValueError, match="unknown manifest fields"):
        Manifest.from_dict(wire)


def test_device_flow_rejects_unknown_fields():
    wire = _flow("dev-a").to_dict()
    wire["extra"] = "bad"
    with pytest.raises(ValueError, match="unknown device flow fields"):
        DeviceFlow.from_dict(wire)


def test_sink_config_rejects_unknown_fields():
    wire = _csv_sink("dev-a", "/data/dev-a.csv").to_dict()
    wire["extra"] = "bad"
    with pytest.raises(ValueError, match="unknown sink fields"):
        SinkConfig.from_dict(wire)


def test_device_flow_rejects_mixing_v1_and_v2_shapes():
    wire = _flow("dev-a").to_dict()
    wire["sink_type"] = "csv"
    with pytest.raises(ValueError, match="cannot mix"):
        DeviceFlow.from_dict(wire)


# ---------------------------------------------------------------------------
# secrets / live objects never enter a manifest
# ---------------------------------------------------------------------------


def test_sink_config_rejects_raw_secret_parameter():
    with pytest.raises(ValueError, match="secret"):
        SinkConfig(
            sink_id="dev-a:influx",
            name="influx",
            type=SinkType.INFLUX,
            parameters={"api_token": "super-secret-value"},
        )


def test_sink_config_accepts_env_var_reference_not_token():
    s = SinkConfig(
        sink_id="dev-a:influx",
        name="influx",
        type=SinkType.INFLUX,
        parameters={"api_token_env": "INFLUX_TOKEN", "bucket": "b"},
    )
    assert "api_token_env" in s.parameters
    assert "api_token" not in s.parameters


def test_sink_config_rejects_unknown_registry_parameter():
    with pytest.raises(ValueError, match="unknown"):
        SinkConfig(
            sink_id="dev-a:csv",
            name="csv",
            type=SinkType.CSV,
            parameters={"not_a_real_param": 1},
        )


def test_sink_config_rejects_live_object_parameter():
    with pytest.raises(ValueError):
        SinkConfig(
            sink_id="dev-a:csv",
            name="csv",
            type=SinkType.CSV,
            parameters={"file_path": object()},
        )


# ---------------------------------------------------------------------------
# reject invalid manifest configurations
# ---------------------------------------------------------------------------


def test_manifest_rejects_empty_device_list():
    with pytest.raises(ValueError, match="at least one device flow"):
        Manifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            dataflow_id="df-1",
            policy=PolicyMode.RECOMMEND,
            device_flows=(),
        )


def test_manifest_rejects_duplicate_device_ids():
    with pytest.raises(ValueError, match="duplicate device_id"):
        Manifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            dataflow_id="df-1",
            policy=PolicyMode.RECOMMEND,
            device_flows=(_flow("dev-a", "/data/a.csv"), _flow("dev-a", "/data/a2.csv")),
        )


def test_manifest_rejects_a_sink_location_owned_by_two_sinks():
    with pytest.raises(ValueError, match="sink location"):
        Manifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            dataflow_id="df-1",
            policy=PolicyMode.RECOMMEND,
            device_flows=(
                _flow("dev-a", "/data/shared.csv"),
                _flow("dev-b", "/data/shared.csv"),
            ),
        )


def test_manifest_rejects_unsupported_schema_version():
    wire = _manifest().to_dict()
    wire["schema_version"] = "99"
    with pytest.raises(ValueError, match="unsupported manifest schema version"):
        Manifest.from_dict(wire)


def test_manifest_rejects_non_int_session_id():
    with pytest.raises(ValueError, match="session_id must be an int or None"):
        Manifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            dataflow_id="df-1",
            policy=PolicyMode.RECOMMEND,
            device_flows=(_flow("dev-a"),),
            session_id="not-an-int",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# content hash
# ---------------------------------------------------------------------------


def test_manifest_hash_is_stable_for_equal_content():
    assert _manifest().hash == _manifest().hash


def test_manifest_hash_ignores_incidental_dict_order():
    """Sink parameters built in a different insertion order hash identically."""
    a = SinkConfig(
        sink_id="dev-a:quest",
        name="quest",
        type=SinkType.QUEST,
        parameters={"host": "h", "port": 9009, "measurement": "m"},
    )
    b = SinkConfig(
        sink_id="dev-a:quest",
        name="quest",
        type=SinkType.QUEST,
        parameters={"measurement": "m", "port": 9009, "host": "h"},
    )

    def _mk(sink: SinkConfig) -> Manifest:
        return Manifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            dataflow_id="df-1",
            policy=PolicyMode.RECOMMEND,
            device_flows=(
                DeviceFlow(
                    device_id="dev-a",
                    name="device-a",
                    nickname=None,
                    hardware_id="hw-a",
                    port="usb-1",
                    parameters={},
                    sinks=(sink,),
                ),
            ),
        )

    assert _mk(a).hash == _mk(b).hash


def test_manifest_hash_depends_on_sink_order():
    """Sink list order is significant — reordering sinks changes the hash."""
    s1 = SinkConfig(sink_id="s1", name="one", type=SinkType.CSV, parameters={"file_path": "/x"})
    s2 = SinkConfig(sink_id="s2", name="two", type=SinkType.PLOT, parameters={})

    def _mk(sinks) -> Manifest:
        return Manifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            dataflow_id="df-1",
            policy=PolicyMode.RECOMMEND,
            device_flows=(
                DeviceFlow(
                    device_id="dev-a",
                    name="device-a",
                    nickname=None,
                    hardware_id="hw-a",
                    port="usb-1",
                    parameters={},
                    sinks=sinks,
                ),
            ),
        )

    assert _mk((s1, s2)).hash != _mk((s2, s1)).hash


def test_manifest_hash_differs_for_different_dataflow_id():
    m1 = _manifest()
    m2 = Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        dataflow_id="df-2",
        policy=PolicyMode.RECOMMEND,
        device_flows=(_flow("dev-a"), _flow("dev-b")),
    )
    assert m1.hash != m2.hash


def test_manifest_hash_differs_for_different_policy():
    m1 = Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        dataflow_id="df-1",
        policy=PolicyMode.RECOMMEND,
        device_flows=(_flow("dev-a"),),
    )
    m2 = Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        dataflow_id="df-1",
        policy=PolicyMode.AUTOMATE,
        device_flows=(_flow("dev-a"),),
    )
    assert m1.hash != m2.hash


def test_manifest_hash_differs_for_different_session_id():
    assert _manifest(session_id=1).hash != _manifest(session_id=2).hash


def test_manifest_hash_differs_for_different_parameters():
    def _flow_with_params(params: dict) -> DeviceFlow:
        return DeviceFlow(
            device_id="dev-a",
            name="device-a",
            nickname=None,
            hardware_id="hw-a",
            port="usb-1",
            parameters=params,
            sinks=(_csv_sink("dev-a", "/data/dev-a.csv"),),
        )

    m1 = Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        dataflow_id="df-1",
        policy=PolicyMode.RECOMMEND,
        device_flows=(_flow_with_params({"sample_rate": 250}),),
    )
    m2 = Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        dataflow_id="df-1",
        policy=PolicyMode.RECOMMEND,
        device_flows=(_flow_with_params({"sample_rate": 500}),),
    )
    assert m1.hash != m2.hash


def test_manifest_hash_differs_for_different_sink_parameters():
    m1 = _manifest()
    m2 = Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        dataflow_id="df-1",
        policy=PolicyMode.RECOMMEND,
        device_flows=(_flow("dev-a", "/data/other.csv"), _flow("dev-b")),
    )
    assert m1.hash != m2.hash


def test_manifest_hash_is_in_wire_form_as_a_sha256_hex_string():
    wire = _manifest().to_dict()
    assert "hash" in wire
    assert isinstance(wire["hash"], str)
    assert len(wire["hash"]) == 64


def test_manifest_from_dict_rejects_tampered_hash():
    wire = _manifest().to_dict()
    wire["hash"] = "0" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        Manifest.from_dict(wire)


def test_manifest_from_dict_accepts_absent_hash():
    wire = _manifest().to_dict()
    del wire["hash"]
    assert Manifest.from_dict(wire) == _manifest()


# ---------------------------------------------------------------------------
# v1 backward reading (release-critical for adoption / respawn)
# ---------------------------------------------------------------------------


def _v1_flow_wire(device_id: str, location: str) -> dict:
    return {
        "device_id": device_id,
        "name": f"device-{device_id}",
        "nickname": None,
        "hardware_id": f"hw-{device_id}",
        "port": "usb-1",
        "parameters": {"sample_rate": 250},
        "sink_type": "csv",
        "sink_location": location,
    }


def _v1_manifest_wire(with_hash: bool = False) -> dict:
    import hashlib
    import json

    payload = {
        "schema_version": _V1_SCHEMA_VERSION,
        "dataflow_id": "df-1",
        "policy": "recommend",
        "device_flows": [_v1_flow_wire("dev-a", "/data/dev-a.csv")],
    }
    wire = dict(payload)
    if with_hash:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        wire["hash"] = hashlib.sha256(canonical.encode()).hexdigest()
    return wire


def test_v1_manifest_is_read_and_translated_to_v2():
    m = Manifest.from_dict(_v1_manifest_wire())
    # Emits v2, never v1.
    assert m.schema_version == "2"
    assert m.session_id is None
    df = m.device_flows[0]
    assert len(df.sinks) == 1
    sink = df.sinks[0]
    assert sink.type is SinkType.CSV
    assert sink.parameters["file_path"] == "/data/dev-a.csv"
    # Wire form is pure v2.
    assert "sink_type" not in m.to_dict()["device_flows"][0]


def test_v1_device_flow_from_dict_translates_single_sink():
    df = DeviceFlow.from_dict(_v1_flow_wire("dev-a", "/data/dev-a.csv"))
    assert df.sinks[0].sink_id == "dev-a:csv"
    assert df.sink_type is SinkType.CSV  # compat property
    assert df.sink_location == "/data/dev-a.csv"  # compat property


def test_v1_manifest_stored_hash_is_validated():
    wire = _v1_manifest_wire(with_hash=True)
    # Valid stored v1 hash: read succeeds.
    assert Manifest.from_dict(wire).schema_version == "2"


def test_v1_manifest_rejects_tampered_stored_hash():
    wire = _v1_manifest_wire(with_hash=True)
    wire["hash"] = "0" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        Manifest.from_dict(wire)


def test_legacy_construction_keywords_still_supported():
    """manifests.py / supervisor.py build DeviceFlow with legacy kwargs."""
    df = DeviceFlow(
        device_id="pod:1",
        name="pod",
        nickname=None,
        hardware_id="1",
        port="COM3",
        parameters={"preamp_gain": 10},
        sink_type=SinkType.CSV,
        sink_location="/data/pod.csv",
    )
    assert df.sink_type is SinkType.CSV
    assert df.sink_location == "/data/pod.csv"
    assert df.sinks[0].type is SinkType.CSV
