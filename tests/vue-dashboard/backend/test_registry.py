"""Unit tests for the device/sink config registry (Packet 3.1 — parameter model)."""

import pytest

from app.domain.enums import DeviceType, SinkCategory, SinkType
from app.domain.errors import UnknownConfigType
from app.services.registry import lookup_device, lookup_sink, sink_parameter_schema

# ---------------------------------------------------------------------------
# lookup_device — known type, valid parameters
# ---------------------------------------------------------------------------


def test_lookup_device_pod8206hr_minimal_required():
    spec = lookup_device("pod8206hr", {
        "preamp_gain": 10,
        "sample_rate": 2000,
        })
    assert spec.type is DeviceType.POD8206HR
    assert spec.as_dict() == {
        "preamp_gain": 10,
        "sample_rate": 2000,
        }


def test_lookup_device_pod8206hr_full_parameter_set():
    spec = lookup_device(
        "pod8206hr",
        {
            "preamp_gain": 100,
            "sample_rate": 2000,
            "lowpass_ch0": 50,
            "lowpass_ch1": 50,
            "lowpass_ch2": 50,
            "ttl_pin0": 1,
        },
    )
    assert spec.as_dict()["sample_rate"] == 2000
    assert spec.as_dict()["ttl_pin0"] == 1


def test_lookup_device_coerces_string_numbers():
    """Morelia stores most values as strings; equal-but-typed inputs canonicalize the same."""
    a = lookup_device("pod8206hr", {"preamp_gain": 10, "sample_rate": "2000"})
    b = lookup_device("pod8206hr", {"preamp_gain": 10, "sample_rate": 2000})
    assert a == b
    assert a.as_dict()["sample_rate"] == 2000


def test_lookup_device_parameter_insertion_order_does_not_matter():
    a = lookup_device("pod8206hr", {"preamp_gain": 10, "lowpass_ch0": 50, "sample_rate": 2000})
    b = lookup_device("pod8206hr", {"sample_rate": 2000, "lowpass_ch0": 50, "preamp_gain": 10})
    assert a == b
    assert a.parameters == b.parameters


def test_lookup_device_spec_is_frozen_and_hashable():
    spec = lookup_device("pod8206hr", {"preamp_gain": 10, "sample_rate": 2000})
    with pytest.raises((AttributeError, TypeError)):
        spec.type = DeviceType.POD8206HR  # type: ignore[misc]
    assert hash(spec) is not None
    assert {spec}


# ---------------------------------------------------------------------------
# lookup_device — unknown type / never imports
# ---------------------------------------------------------------------------


def test_lookup_device_unknown_type_raises_typed_error():
    with pytest.raises(UnknownConfigType) as exc_info:
        lookup_device("fake_device", {"preamp_gain": 10})
    assert exc_info.value.category == "device"
    assert exc_info.value.type_key == "fake_device"
    assert "fake_device" in str(exc_info.value)


def test_lookup_device_unknown_type_does_not_import():
    with pytest.raises(UnknownConfigType):
        lookup_device("app.devices.Pod8206HR", {})


# ---------------------------------------------------------------------------
# lookup_device — invalid parameters
# ---------------------------------------------------------------------------


def test_lookup_device_missing_required_parameter_raises():
    with pytest.raises(ValueError, match="missing"):
        lookup_device("pod8206hr", {"lowpass_ch0": 50})  # preamp_gain missing


def test_lookup_device_unknown_parameter_raises():
    with pytest.raises(ValueError, match="unknown"):
        lookup_device("pod8206hr", {"preamp_gain": 10, "ttl_port": 3})  # read-only, not writable


def test_lookup_device_bad_preamp_gain_value_raises():
    with pytest.raises(ValueError, match="preamp_gain must be 10 or 100"):
        lookup_device("pod8206hr", {"preamp_gain": 42, "sample_rate": 2000})


def test_lookup_device_preamp_gain_string_coerces_then_validates():
    spec = lookup_device("pod8206hr", {"preamp_gain": "100", "sample_rate": 2000})
    assert spec.as_dict()["preamp_gain"] == 100


def test_lookup_device_pod8401hr_accepts_six_secondary_channel_modes(monkeypatch):
    class _Preamp:
        __members__ = {"Preamp8407_SE": object()}

    monkeypatch.setattr(
        "Morelia.Devices.PodDevice_8401HR._SECONDARY_CHANNEL_MODE_NAMES",
        frozenset({"ANALOG", "DIGITAL"}),
    )

    spec = lookup_device(
        "pod8401hr",
        {
            "preamp": "Preamp8407_SE",
            "primary_channel_modes": ["BIOSENSOR", "EEG_EMG", "EEG_EMG", "EEG_EMG"],
            "secondary_channel_modes": [
                "DIGITAL",
                "DIGITAL",
                "DIGITAL",
                "DIGITAL",
                "DIGITAL",
                "DIGITAL",
            ],
            "ss_gain": [1, 5, 5, 5],
            "preamp_gain": [None, 10, 10, 10],
        },
    )

    assert spec.as_dict()["secondary_channel_modes"] == (
        "DIGITAL",
        "DIGITAL",
        "DIGITAL",
        "DIGITAL",
        "DIGITAL",
        "DIGITAL",
    )


def test_lookup_device_pod8401hr_rejects_four_secondary_channel_modes(monkeypatch):
    class _Preamp:
        __members__ = {"Preamp8407_SE": object()}

    monkeypatch.setattr(
        "Morelia.Devices.PodDevice_8401HR._SECONDARY_CHANNEL_MODE_NAMES",
        frozenset({"ANALOG", "DIGITAL"}),
    )

    with pytest.raises(ValueError, match="secondary_channel_modes must be a 6-tuple"):
        lookup_device(
            "pod8401hr",
            {
                "preamp": "Preamp8407_SE",
                "primary_channel_modes": ["BIOSENSOR", "EEG_EMG", "EEG_EMG", "EEG_EMG"],
                "secondary_channel_modes": ["DIGITAL", "DIGITAL", "DIGITAL", "DIGITAL"],
            },
        )


# ---------------------------------------------------------------------------
# lookup_sink
# ---------------------------------------------------------------------------


def test_lookup_sink_csv_with_location():
    spec = lookup_sink("csv", {"file_path": "/data/run1.csv"})
    assert spec.type is SinkType.CSV
    assert spec.as_dict() == {"file_path": "/data/run1.csv"}


def test_lookup_sink_csv_without_location_is_allowed():
    """Location is optional — Stage 4 allocates a safe segment when absent."""
    spec = lookup_sink("csv", {})
    assert spec.type is SinkType.CSV
    assert spec.as_dict() == {}


def test_lookup_sink_unknown_type_raises_typed_error():
    with pytest.raises(UnknownConfigType) as exc_info:
        lookup_sink("parquet", {"file_path": "/tmp/x.parquet"})
    assert exc_info.value.category == "sink"
    assert exc_info.value.type_key == "parquet"


def test_lookup_sink_unknown_parameter_raises():
    with pytest.raises(ValueError, match="unknown"):
        lookup_sink("csv", {"file_path": "/data/run1.csv", "delimiter": ","})


def test_lookup_sink_spec_is_frozen_and_hashable():
    spec = lookup_sink("csv", {"file_path": "/data/run1.csv"})
    with pytest.raises((AttributeError, TypeError)):
        spec.type = SinkType.CSV  # type: ignore[misc]
    assert {spec}


# ---------------------------------------------------------------------------
# lookup_sink — all six approved types, exactly, with stable categories
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("type_key", "category"),
    [
        ("csv", SinkCategory.FILE),
        ("edf", SinkCategory.FILE),
        ("pvfs", SinkCategory.FILE),
        ("influx", SinkCategory.SERVICE),
        ("quest", SinkCategory.SERVICE),
        ("plot", SinkCategory.PLOT),
    ],
)
def test_lookup_sink_recognizes_each_approved_type_with_its_category(type_key, category):
    parameters = {"api_token_env": "INFLUX_TOKEN"} if type_key == "influx" else {}
    spec = lookup_sink(type_key, parameters)
    assert spec.type is SinkType(type_key)
    assert spec.category is category


def test_lookup_sink_approved_types_are_exactly_six():
    assert {member.value for member in SinkType} == {
        "csv",
        "edf",
        "pvfs",
        "influx",
        "quest",
        "plot",
    }


# ---------------------------------------------------------------------------
# lookup_sink — edf / pvfs file sinks
# ---------------------------------------------------------------------------


def test_lookup_sink_edf_with_location_and_scheduler():
    spec = lookup_sink(
        "edf", {"file_path": "/data/run1.edf", "observe_on_scheduler": "thread_pool"}
    )
    assert spec.as_dict() == {
        "file_path": "/data/run1.edf",
        "observe_on_scheduler": "thread_pool",
    }


def test_lookup_sink_edf_bad_observe_on_scheduler_raises():
    with pytest.raises(ValueError, match="observe_on_scheduler"):
        lookup_sink("edf", {"observe_on_scheduler": "background"})


def test_lookup_sink_pvfs_with_writer_process_flag():
    spec = lookup_sink("pvfs", {"use_writer_process": True})
    assert spec.as_dict() == {"use_writer_process": True}


def test_lookup_sink_pvfs_use_writer_process_must_be_boolean():
    with pytest.raises(ValueError, match="use_writer_process"):
        lookup_sink("pvfs", {"use_writer_process": "yes"})


def test_lookup_sink_pvfs_accepts_pinned_device_preferences_shape():
    spec = lookup_sink(
        "pvfs",
        {
            "device_preferences": [
                {
                    "name": "gain",
                    "type": "int",
                    "value": "10",
                    "ProductNumber": "8206HR",
                    "SerialNumber": "SN123",
                }
            ]
        },
    )
    assert spec.as_dict()["device_preferences"] == (
        {
            "name": "gain",
            "type": "int",
            "value": "10",
            "ProductNumber": "8206HR",
            "SerialNumber": "SN123",
        },
    )


def test_lookup_sink_pvfs_rejects_device_preferences_with_extra_keys():
    """SINK-17: only the pinned pvfs_tools shape is accepted, not arbitrary dicts."""
    with pytest.raises(ValueError, match="device_preferences"):
        lookup_sink(
            "pvfs",
            {
                "device_preferences": [
                    {
                        "name": "gain",
                        "type": "int",
                        "value": "10",
                        "ProductNumber": "8206HR",
                        "SerialNumber": "SN123",
                        "extra": "nope",
                    }
                ]
            },
        )


def test_lookup_sink_pvfs_rejects_device_preferences_with_missing_keys():
    with pytest.raises(ValueError, match="device_preferences"):
        lookup_sink("pvfs", {"device_preferences": [{"name": "gain"}]})


def test_lookup_sink_pvfs_rejects_non_list_device_preferences():
    with pytest.raises(ValueError, match="device_preferences"):
        lookup_sink("pvfs", {"device_preferences": {"name": "gain"}})


# ---------------------------------------------------------------------------
# lookup_sink — influx (service, secret reference only)
# ---------------------------------------------------------------------------


def test_lookup_sink_influx_requires_api_token_env():
    with pytest.raises(ValueError, match="missing"):
        lookup_sink("influx", {})


def test_lookup_sink_influx_accepts_full_parameter_set():
    spec = lookup_sink(
        "influx",
        {
            "api_token_env": "INFLUX_TOKEN",
            "url": "http://localhost:8086",
            "org": "lab",
            "bucket": "recordings",
            "measurement": "experiment_a",
            "buffer_max_age_seconds": 30,
            "buffer_max_bytes": 1024,
        },
    )
    assert spec.as_dict()["api_token_env"] == "INFLUX_TOKEN"
    assert spec.as_dict()["buffer_max_bytes"] == 1024


def test_lookup_sink_influx_rejects_file_path():
    """Service sinks reject sink_location rather than ignoring it (design doc rule 6)."""
    with pytest.raises(ValueError, match="unknown"):
        lookup_sink("influx", {"api_token_env": "INFLUX_TOKEN", "file_path": "/data/x.csv"})


def test_lookup_sink_influx_rejects_a_literal_token_parameter():
    """No schema accepts a token value — only an env-var reference."""
    with pytest.raises(ValueError, match="unknown"):
        lookup_sink("influx", {"api_token_env": "INFLUX_TOKEN", "token": "secret-value"})


@pytest.mark.parametrize("bad_env", ["", "   "])
def test_lookup_sink_influx_api_token_env_must_be_nonempty(bad_env):
    with pytest.raises(ValueError, match="api_token_env"):
        lookup_sink("influx", {"api_token_env": bad_env})


def test_lookup_sink_influx_buffer_max_bytes_must_be_positive():
    with pytest.raises(ValueError, match="buffer_max_bytes"):
        lookup_sink("influx", {"api_token_env": "INFLUX_TOKEN", "buffer_max_bytes": 0})


def test_lookup_sink_no_sink_schema_accepts_a_secret_valued_parameter():
    """No approved sink type's schema accepts token/password/secret values —
    only influx's api_token_env, which is an env-var name reference."""
    for type_key in ("csv", "edf", "pvfs", "influx", "quest", "plot"):
        schema = sink_parameter_schema(type_key)
        known = {*schema["required"], *schema["optional"]}
        assert known.isdisjoint({"token", "api_token", "password", "secret"})


# ---------------------------------------------------------------------------
# lookup_sink — quest (service)
# ---------------------------------------------------------------------------


def test_lookup_sink_quest_defaults_are_all_optional():
    spec = lookup_sink("quest", {})
    assert spec.as_dict() == {}


def test_lookup_sink_quest_accepts_host_and_port():
    spec = lookup_sink("quest", {"host": "localhost", "port": 9009})
    assert spec.as_dict() == {"host": "localhost", "port": 9009}


@pytest.mark.parametrize("bad_port", [0, 65536, -1, "not-a-port"])
def test_lookup_sink_quest_port_must_be_in_valid_range(bad_port):
    with pytest.raises(ValueError, match="port"):
        lookup_sink("quest", {"port": bad_port})


def test_lookup_sink_quest_rejects_file_path():
    with pytest.raises(ValueError, match="unknown"):
        lookup_sink("quest", {"file_path": "/data/x.csv"})


# ---------------------------------------------------------------------------
# lookup_sink — plot (no durable recording, no location)
# ---------------------------------------------------------------------------


def test_lookup_sink_plot_defaults_are_all_optional():
    spec = lookup_sink("plot", {})
    assert spec.as_dict() == {}


def test_lookup_sink_plot_accepts_display_parameters():
    spec = lookup_sink(
        "plot",
        {"chunk_samples": 50, "max_display_rate": 30.0, "channel_names": ["EEG1", "EEG2"]},
    )
    assert spec.as_dict() == {
        "chunk_samples": 50,
        "max_display_rate": 30.0,
        "channel_names": ("EEG1", "EEG2"),
    }


def test_lookup_sink_plot_rejects_file_path():
    with pytest.raises(ValueError, match="unknown"):
        lookup_sink("plot", {"file_path": "/data/x.csv"})


@pytest.mark.parametrize("bad_chunk_samples", [0, -5, "many"])
def test_lookup_sink_plot_chunk_samples_must_be_a_positive_int(bad_chunk_samples):
    with pytest.raises(ValueError, match="chunk_samples"):
        lookup_sink("plot", {"chunk_samples": bad_chunk_samples})


def test_lookup_sink_plot_channel_names_must_be_nonempty_strings():
    with pytest.raises(ValueError, match="channel_names"):
        lookup_sink("plot", {"channel_names": ["EEG1", ""]})


def test_lookup_sink_plot_channel_names_must_not_be_empty_list():
    with pytest.raises(ValueError, match="channel_names"):
        lookup_sink("plot", {"channel_names": []})


# ---------------------------------------------------------------------------
# sink_parameter_schema — introspection for future config/CLI packets
# ---------------------------------------------------------------------------


def test_sink_parameter_schema_reports_category_and_keys():
    schema = sink_parameter_schema("influx")
    assert schema == {
        "category": "service",
        "required": ["api_token_env"],
        "optional": sorted(
            [
                "url",
                "org",
                "bucket",
                "measurement",
                "observe_on_scheduler",
                "buffer_max_age_seconds",
                "buffer_max_bytes",
            ]
        ),
    }


def test_sink_parameter_schema_unknown_type_raises_typed_error():
    with pytest.raises(UnknownConfigType) as exc_info:
        sink_parameter_schema("parquet")
    assert exc_info.value.category == "sink"
    assert exc_info.value.type_key == "parquet"
