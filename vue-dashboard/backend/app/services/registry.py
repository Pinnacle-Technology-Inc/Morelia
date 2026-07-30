"""Typed device/sink registry — the closed vocabulary of supported config.

A *device template* names a device ``type`` and a flat map of writable
``parameters``. The registry validates the type key, rejects unknown parameter
keys, coerces string scalars to numbers (Morelia stores most values as
strings), and runs light per-parameter value checks. It returns a canonical,
frozen spec consumed by the device-template store (3.2) and snapshotted into the
runtime manifest (3.5). Pure/stateless — no I/O, no DB, no Flask.

Parameter sets are pinned from the Morelia device property maps + setters:
  - ``pod8206hr`` — ``src/Morelia/Devices/PodDevice_8206HR.py``
      construction: ``preamp_gain`` (10 or 100; required to build the device)
      writable:     ``sample_rate``, ``lowpass_ch0/1/2``, ``ttl_pin0..3``
      (read-only ``ttl_port`` / ``filter_config`` are excluded — not settable)
  - ``pod8401hr`` — ``src/Morelia/Devices/PodDevice_8401HR.py``
      construction: ``preamp``, ``primary_channel_modes``, ``secondary_channel_modes``
      (required); ``ss_gain``, ``preamp_gain`` (optional, 4-tuples, default no-connect)
      Other ``DeviceType`` members have no pinned schema yet and raise
      ``UnsupportedDeviceType`` until their parameter set is pinned here.

Construction-only transport (``port``, ``device_name``, ``baudrate``) is NOT a
parameter — it is session binding, supplied per run (3.3). ``preamp_gain`` is a
reusable hardware parameter (which preamp is attached), so it lives in the
device template.

Usage::

    spec = lookup_device("pod8206hr", {"preamp_gain": 10, "lowpass_ch0": 50})
    spec = lookup_sink("csv", {"file_path": "/data/run1.csv"})
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import ClassVar

from app.domain.enums import DeviceType, SinkCategory, SinkType
from app.domain.errors import UnknownConfigType, UnsupportedDeviceType

# ---------------------------------------------------------------------------
# Value coercion — mirror Morelia's apply-time normalization so a TOML string
# ("2000") and a native number (2000) canonicalize identically (feeds 3.2's
# hash stability). Matches Morelia: str.isdigit() -> int; single-dot -> float;
# everything else (incl. signed strings, bools, non-strings) left unchanged.
# ---------------------------------------------------------------------------


def _coerce_scalar(value: object) -> object:
    if isinstance(value, bool) or not isinstance(value, str):
        return value
    s = value.strip()
    if s.isdigit():
        return int(s)
    if s.count(".") == 1 and s.replace(".", "", 1).isdigit():
        return float(s)
    return value


def _normalize_container(value: object) -> object:
    """Canonicalize JSON-decoded arrays to tuples before validation.

    Sequence parameters are modeled as Python tuples, but a caller passing a
    JSON request body will hand us a ``list`` instead. Normalize here so both
    shapes validate identically.
    """
    if isinstance(value, list):
        return tuple(value)
    return value


# ---------------------------------------------------------------------------
# Per-type parameter schema: required + optional keys, plus optional value
# validators for the few high-value constraints. Extensible: add a device type
# by adding an entry here (e.g. pod8401hr from its richer _property_map).
# ---------------------------------------------------------------------------


def _check_preamp_gain(value: object) -> None:
    if value not in (10, 100):
        raise ValueError("preamp_gain must be 10 or 100")


# -- pod8401hr validators ----------------------------------------------------
# Source of truth: Morelia.Devices.PodDevice_8401HR.Pod8401HR and
# DataPacket8401HR. Morelia's constructor takes a Preamp enum member, a
# PrimaryChannelMode 4-tuple for primary channels A-D, and a
# SecondaryChannelMode 6-tuple for EXT0, EXT1, TTL1, TTL2, TTL3, TTL4. Our
# registry stores JSON-serializable canonical scalars instead of live Morelia
# enum objects, so each is represented as its member-name string(s).

_PRIMARY_CHANNEL_MODE_NAMES = frozenset({"EEG_EMG", "BIOSENSOR"})
_SECONDARY_CHANNEL_MODE_NAMES = frozenset({"ANALOG", "DIGITAL"})


def _import_preamp_enum() -> type:
    """Import Morelia's ``Preamp`` enum lazily, honoring ``MORELIA_SRC`` like
    ``app/discovery/pod_scan.py`` does — keeps this module importable without
    Morelia installed; only paid for when a pod8401hr ``preamp`` value is
    actually validated.
    """
    import importlib
    import os
    import sys

    morelia_src = os.environ.get("MORELIA_SRC")
    if morelia_src and morelia_src not in sys.path:
        sys.path.insert(0, morelia_src)

    module = importlib.import_module("Morelia.Devices.preamp")
    return module.Preamp


def _check_preamp(value: object) -> None:
    preamp_enum = _import_preamp_enum()
    if value not in preamp_enum.__members__:
        raise ValueError(
            f"preamp must be one of {sorted(preamp_enum.__members__)}; got {value!r}"
        )


def _check_four_tuple(value: object, allowed: frozenset[str], key: str) -> None:
    if not isinstance(value, tuple) or len(value) != 4:
        raise ValueError(f"{key} must be a 4-tuple (one per channel A-D)")
    _check_tuple_values(value, allowed, key)


def _check_six_tuple(value: object, allowed: frozenset[str], key: str) -> None:
    if not isinstance(value, tuple) or len(value) != 6:
        raise ValueError(f"{key} must be a 6-tuple (EXT0, EXT1, TTL1, TTL2, TTL3, TTL4)")
    _check_tuple_values(value, allowed, key)


def _check_tuple_values(value: tuple[object, ...], allowed: frozenset[str], key: str) -> None:
    bad = [v for v in value if v not in allowed]
    if bad:
        raise ValueError(f"{key} elements must be one of {sorted(allowed)}; got {bad!r}")


def _check_primary_channel_modes(value: object) -> None:
    _check_four_tuple(value, _PRIMARY_CHANNEL_MODE_NAMES, "primary_channel_modes")


def _check_secondary_channel_modes(value: object) -> None:
    _check_six_tuple(value, _SECONDARY_CHANNEL_MODE_NAMES, "secondary_channel_modes")


def _check_ss_gain(value: object) -> None:
    if not isinstance(value, tuple) or len(value) != 4:
        raise ValueError("ss_gain must be a 4-tuple (one per channel A-D)")
    for v in value:
        if v != 1 and v != 5 and v is not None:
            raise ValueError("ss_gain must be 1 or 5; set ss_gain to None if no-connect")


def _check_preamp_gain_tuple(value: object) -> None:
    if not isinstance(value, tuple) or len(value) != 4:
        raise ValueError("preamp_gain must be a 4-tuple (one per channel A-D)")
    for v in value:
        if v != 10 and v != 100 and v is not None:
            raise ValueError(
                "preamp_gain must be 10 or 100; for biosensors, preamp_gain is None"
            )


# -- sink validators ----------------------------------------------------------
# Shared, type-agnostic checks reused across the file/service/plot sink
# schemas below. Each is bound to its field name via functools.partial so it
# fits the single-argument Callable[[object], None] shape ParamSchema expects.

_OBSERVE_ON_SCHEDULER_VALUES = frozenset({None, "thread_pool", "new_thread"})


def _check_observe_on_scheduler(value: object) -> None:
    if value not in _OBSERVE_ON_SCHEDULER_VALUES:
        raise ValueError('observe_on_scheduler must be one of: null, "thread_pool", "new_thread"')


def _check_nonempty_string(value: object, *, key: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")


def _check_port(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not (1 <= value <= 65535):
        raise ValueError("port must be an integer in 1..65535")


def _check_positive_number(value: object, *, key: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{key} must be a positive number")


def _check_positive_int(value: object, *, key: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{key} must be a positive integer")


def _check_bool(value: object, *, key: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")


def _check_pvfs_writer_process(value: object) -> None:
    _check_bool(value, key="use_writer_process")
    if value is not True:
        raise ValueError("use_writer_process cannot be disabled for PVFS sinks")


def _check_channel_names(value: object) -> None:
    if not isinstance(value, tuple) or not value:
        raise ValueError("channel_names must be a non-empty list of non-empty strings")
    for name in value:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("channel_names must be a non-empty list of non-empty strings")


# PVFS device_preferences: pinned to the one enforceable shape the installed
# pvfs_tools library actually accepts (pvfs_tools.Database.database.Database.
# set_device_preferences / pvfs_data_file.PvfsDataFile.set_device_preferences)
# — a list of flat objects with exactly these five string fields. Per SINK-17,
# arbitrary dictionaries are rejected rather than passed through.
_DEVICE_PREFERENCE_KEYS = frozenset({"name", "type", "value", "ProductNumber", "SerialNumber"})
_DEVICE_PREFERENCE_STRING_KEYS = ("name", "type", "ProductNumber", "SerialNumber")


def _check_device_preferences(value: object) -> None:
    if not isinstance(value, tuple):
        raise ValueError("device_preferences must be a list of preference objects")
    for entry in value:
        if not isinstance(entry, Mapping):
            raise ValueError("each device_preferences entry must be an object")
        keys = set(entry)
        if keys != _DEVICE_PREFERENCE_KEYS:
            missing = _DEVICE_PREFERENCE_KEYS - keys
            unknown = keys - _DEVICE_PREFERENCE_KEYS
            parts = []
            if missing:
                parts.append(f"missing {', '.join(sorted(missing))}")
            if unknown:
                parts.append(f"unknown {', '.join(sorted(unknown))}")
            raise ValueError(f"device_preferences entry has {'; '.join(parts)}")
        for key in _DEVICE_PREFERENCE_STRING_KEYS:
            if not isinstance(entry[key], str) or not entry[key].strip():
                raise ValueError(f"device_preferences entry {key!r} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class ParamSchema:
    required: frozenset[str]
    optional: frozenset[str]
    validators: Mapping[str, Callable[[object], None]] = None  # type: ignore[assignment]

    @property
    def known(self) -> frozenset[str]:
        return self.required | self.optional


_DEVICE_SCHEMA: dict[DeviceType, ParamSchema] = {
    DeviceType.POD8206HR: ParamSchema(
        required=frozenset({"preamp_gain"}),
        optional=frozenset(
            {
                "sample_rate",
                "lowpass_ch0",
                "lowpass_ch1",
                "lowpass_ch2",
                "ttl_pin0",
                "ttl_pin1",
                "ttl_pin2",
                "ttl_pin3",
            }
        ),
        validators={"preamp_gain": _check_preamp_gain},
    ),
    DeviceType.POD8401HR: ParamSchema(
        required=frozenset(
            {"preamp", "primary_channel_modes", "secondary_channel_modes"}
        ),
        optional=frozenset({"ss_gain", "preamp_gain"}),
        validators={
            "preamp": _check_preamp,
            "primary_channel_modes": _check_primary_channel_modes,
            "secondary_channel_modes": _check_secondary_channel_modes,
            "ss_gain": _check_ss_gain,
            "preamp_gain": _check_preamp_gain_tuple,
        },
    ),
}
# POD8229 / POD8274D / POD8480SC / UNKNOWN intentionally have no entry here —
# they raise UnsupportedDeviceType (see DeviceSpec.from_dict) until pinned.

# Stable category per sink type — drives shared contract rules (e.g. which
# types may resolve a sink_location) without re-deriving them from the type.
# See docs/all-sink-support-design-and-gap-audit.md section 3 "Sink categories".
_SINK_CATEGORY: dict[SinkType, SinkCategory] = {
    SinkType.CSV: SinkCategory.FILE,
    SinkType.EDF: SinkCategory.FILE,
    SinkType.PVFS: SinkCategory.FILE,
    SinkType.INFLUX: SinkCategory.SERVICE,
    SinkType.QUEST: SinkCategory.SERVICE,
    SinkType.PLOT: SinkCategory.PLOT,
}

# File sinks carry no required keys here: the output location is optional
# (the segment allocator assigns a safe path when absent) and is resolved at
# the session layer. ``file_path`` is accepted so the existing sink_location
# resolution path (app.services.session_config._resolve_sink) continues to
# work unchanged for every file-category type; service/plot schemas omit it
# so the same path rejects a sink_location for those types instead of
# silently ignoring it (design doc section 4, rule 6).
_SINK_SCHEMA: dict[SinkType, ParamSchema] = {
    SinkType.CSV: ParamSchema(
        required=frozenset(),
        optional=frozenset({"file_path", "observe_on_scheduler"}),
        validators={"observe_on_scheduler": _check_observe_on_scheduler},
    ),
    SinkType.EDF: ParamSchema(
        required=frozenset(),
        optional=frozenset({"file_path", "observe_on_scheduler"}),
        validators={"observe_on_scheduler": _check_observe_on_scheduler},
    ),
    SinkType.PVFS: ParamSchema(
        required=frozenset(),
        optional=frozenset(
            {"file_path", "observe_on_scheduler", "use_writer_process", "device_preferences"}
        ),
        validators={
            "observe_on_scheduler": _check_observe_on_scheduler,
            "use_writer_process": _check_pvfs_writer_process,
            "device_preferences": _check_device_preferences,
        },
    ),
    # api_token_env is an environment-variable *reference*, never the token
    # value itself — see docs section 4 "Secrets". No schema in this registry
    # accepts a literal token/password/secret parameter.
    SinkType.INFLUX: ParamSchema(
        required=frozenset({"api_token_env"}),
        optional=frozenset(
            {
                "url",
                "org",
                "bucket",
                "measurement",
                "observe_on_scheduler",
                "buffer_max_age_seconds",
                "buffer_max_bytes",
            }
        ),
        validators={
            "api_token_env": partial(_check_nonempty_string, key="api_token_env"),
            "url": partial(_check_nonempty_string, key="url"),
            "org": partial(_check_nonempty_string, key="org"),
            "bucket": partial(_check_nonempty_string, key="bucket"),
            "measurement": partial(_check_nonempty_string, key="measurement"),
            "observe_on_scheduler": _check_observe_on_scheduler,
            "buffer_max_age_seconds": partial(_check_positive_number, key="buffer_max_age_seconds"),
            "buffer_max_bytes": partial(_check_positive_int, key="buffer_max_bytes"),
        },
    ),
    SinkType.QUEST: ParamSchema(
        required=frozenset(),
        optional=frozenset(
            {
                "host",
                "port",
                "measurement",
                "observe_on_scheduler",
                "buffer_max_age_seconds",
                "buffer_max_bytes",
            }
        ),
        validators={
            "host": partial(_check_nonempty_string, key="host"),
            "port": _check_port,
            "measurement": partial(_check_nonempty_string, key="measurement"),
            "observe_on_scheduler": _check_observe_on_scheduler,
            "buffer_max_age_seconds": partial(_check_positive_number, key="buffer_max_age_seconds"),
            "buffer_max_bytes": partial(_check_positive_int, key="buffer_max_bytes"),
        },
    ),
    SinkType.PLOT: ParamSchema(
        required=frozenset(),
        optional=frozenset({"chunk_samples", "max_display_rate", "channel_names"}),
        validators={
            "chunk_samples": partial(_check_positive_int, key="chunk_samples"),
            "max_display_rate": partial(_check_positive_number, key="max_display_rate"),
            "channel_names": _check_channel_names,
        },
    ),
}


def _validate(
    category: str,
    type_key: str,
    schema: ParamSchema,
    values: Mapping[str, object],
) -> dict[str, object]:
    """Reject unknown/missing keys, coerce scalars, run value checks."""
    unknown = set(values) - schema.known
    if unknown:
        raise ValueError(
            f"unknown {type_key!r} {category} parameters: {', '.join(sorted(unknown))}"
        )
    missing = schema.required - set(values)
    if missing:
        raise ValueError(
            f"missing {type_key!r} {category} parameters: {', '.join(sorted(missing))}"
        )

    coerced = {k: _coerce_scalar(_normalize_container(v)) for k, v in values.items()}
    if schema.validators:
        for key, check in schema.validators.items():
            if key in coerced:
                check(coerced[key])
    return coerced


# ---------------------------------------------------------------------------
# Value objects — frozen, hashable, canonical-ordered. Parameters are stored as
# a sorted tuple-of-items so equal inputs (any insertion order) compare equal.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeviceSpec:
    """Canonical, validated parameter set for one device template."""

    type: DeviceType
    parameters: tuple[tuple[str, object], ...]

    _SCHEMA: ClassVar[dict[DeviceType, ParamSchema]] = _DEVICE_SCHEMA

    @classmethod
    def from_dict(cls, type_key: str, values: Mapping[str, object]) -> DeviceSpec:
        try:
            device_type = DeviceType(type_key)
        except ValueError:
            raise UnknownConfigType("device", type_key) from None

        schema = cls._SCHEMA.get(device_type)
        if schema is None:
            raise UnsupportedDeviceType(type_key)

        coerced = _validate("device", type_key, schema, values)
        return cls(type=device_type, parameters=tuple(sorted(coerced.items())))

    def as_dict(self) -> dict[str, object]:
        return dict(self.parameters)


@dataclass(frozen=True, slots=True)
class SinkSpec:
    """Canonical, validated spec for a data sink."""

    type: SinkType
    category: SinkCategory
    parameters: tuple[tuple[str, object], ...]

    _SCHEMA: ClassVar[dict[SinkType, ParamSchema]] = _SINK_SCHEMA
    _CATEGORY: ClassVar[dict[SinkType, SinkCategory]] = _SINK_CATEGORY

    @classmethod
    def from_dict(cls, type_key: str, values: Mapping[str, object]) -> SinkSpec:
        try:
            sink_type = SinkType(type_key)
        except ValueError:
            raise UnknownConfigType("sink", type_key) from None

        coerced = _validate("sink", type_key, cls._SCHEMA[sink_type], values)
        return cls(
            type=sink_type,
            category=cls._CATEGORY[sink_type],
            parameters=tuple(sorted(coerced.items())),
        )

    def as_dict(self) -> dict[str, object]:
        return dict(self.parameters)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def lookup_device(type_key: str, parameters: Mapping[str, object]) -> DeviceSpec:
    """Return the canonical DeviceSpec for *type_key*, validating *parameters*.

    Raises:
        UnknownConfigType: if *type_key* is not a valid DeviceType at all.
        UnsupportedDeviceType: if *type_key* is a valid DeviceType but has no
            pinned parameter schema yet.
        ValueError: unknown/missing parameter key, or a failed value check.
    """
    return DeviceSpec.from_dict(type_key, parameters)


def lookup_sink(type_key: str, parameters: Mapping[str, object]) -> SinkSpec:
    """Return the canonical SinkSpec for *type_key*, validating *parameters*.

    Raises:
        UnknownConfigType: if *type_key* is not a supported sink type.
        ValueError: unknown parameter key for the sink type.
    """
    return SinkSpec.from_dict(type_key, parameters)


def device_parameter_schema(type_key: str) -> dict[str, list[str]]:
    """Return promptable parameter keys for a supported device type."""
    try:
        device_type = DeviceType(type_key)
    except ValueError:
        raise UnknownConfigType("device", type_key) from None

    schema = _DEVICE_SCHEMA.get(device_type)
    if schema is None:
        raise UnsupportedDeviceType(type_key)

    return {
        "required": sorted(schema.required),
        "optional": sorted(schema.optional),
    }


def sink_parameter_schema(type_key: str) -> dict[str, object]:
    """Return the category and promptable parameter keys for a supported sink type."""
    try:
        sink_type = SinkType(type_key)
    except ValueError:
        raise UnknownConfigType("sink", type_key) from None

    schema = _SINK_SCHEMA[sink_type]
    return {
        "category": _SINK_CATEGORY[sink_type].value,
        "required": sorted(schema.required),
        "optional": sorted(schema.optional),
    }
