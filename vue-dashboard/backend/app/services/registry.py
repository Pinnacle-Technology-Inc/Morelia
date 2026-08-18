"""Typed device/sink registry for supported configuration types.

The registry owns the dashboard's closed type vocabulary, sink categories,
canonical scalar normalization, and stable lookup/introspection API. Morelia
device and sink classes own parameter keys and validators through their
``param_schema`` properties; this module loads those schemas lazily without
running constructors, opening hardware, or allocating sink resources.

Usage::

    spec = lookup_device("pod8206hr", {"preamp_gain": 10, "sample_rate": 2000})
    spec = lookup_sink("csv", {"file_path": "/data/run1.csv"})
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib import import_module
from typing import TYPE_CHECKING, ClassVar, TypeAlias

from app.domain.enums import DeviceType, SinkCategory, SinkType
from app.domain.errors import UnknownConfigType, UnsupportedDeviceType

if TYPE_CHECKING:
    from Morelia.ParamSchema.ParamSchema import ParamSchema


# Morelia stores many scalar settings as strings. Keep normalization in this
# boundary adapter so JSON/TOML callers receive stable, hashable value objects.
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
    """Canonicalize JSON-decoded arrays to tuples before validation."""
    if isinstance(value, list):
        return tuple(value)
    return value


MoreliaType: TypeAlias = tuple[str, str]

_DEVICE_MORELIA_TYPES: dict[DeviceType, MoreliaType] = {
    DeviceType.POD8206HR: ("Morelia.Devices.PodDevice_8206HR", "Pod8206HR"),
    DeviceType.POD8274D: ("Morelia.Devices.PodDevice_8274D", "Pod8274D"),
    DeviceType.POD8401HR: ("Morelia.Devices.PodDevice_8401HR", "Pod8401HR"),
}

_DEFAULT_SAMPLE_RATE = 2_000
_DEFAULT_SAMPLE_RATE_DEVICE_TYPES = frozenset(
    {DeviceType.POD8206HR, DeviceType.POD8401HR}
)

_SINK_MORELIA_TYPES: dict[SinkType, MoreliaType] = {
    SinkType.CSV: ("Morelia.Stream.sink.csv_sink", "CSVSink"),
    SinkType.EDF: ("Morelia.Stream.sink.edf_sink", "EDFSink"),
    SinkType.PVFS: ("Morelia.Stream.sink.pvfs_sink", "PvfsSink"),
    SinkType.INFLUX: ("Morelia.Stream.sink.influx_sink", "InfluxSink"),
    SinkType.QUEST: ("Morelia.Stream.sink.quest_sink", "QuestSink"),
    SinkType.PLOT: ("Morelia.Stream.sink.plot_sink", "PlotSink"),
}

_SINK_CATEGORY: dict[SinkType, SinkCategory] = {
    SinkType.CSV: SinkCategory.FILE,
    SinkType.EDF: SinkCategory.FILE,
    SinkType.PVFS: SinkCategory.FILE,
    SinkType.INFLUX: SinkCategory.SERVICE,
    SinkType.QUEST: SinkCategory.SERVICE,
    SinkType.PLOT: SinkCategory.PLOT,
}


@cache
def _load_param_schema(morelia_type: MoreliaType) -> ParamSchema:
    """Load a Morelia-owned schema without running the provider constructor."""
    morelia_src = os.environ.get("MORELIA_SRC")
    if morelia_src and morelia_src not in sys.path:
        sys.path.insert(0, morelia_src)

    module_name, class_name = morelia_type
    provider_type = getattr(import_module(module_name), class_name)
    schema = object.__new__(provider_type).param_schema
    missing = [
        attribute
        for attribute in ("required", "optional", "known", "validators")
        if not hasattr(schema, attribute)
    ]
    if missing:
        raise TypeError(
            f"{module_name}.{class_name}.param_schema is missing: {', '.join(missing)}"
        )
    return schema


def _validate(
    category: str,
    type_key: str,
    schema: ParamSchema,
    values: Mapping[str, object],
) -> dict[str, object]:
    """Reject unknown/missing keys, coerce scalars, and run Morelia checks."""
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


@dataclass(frozen=True, slots=True)
class DeviceSpec:
    """Canonical, validated parameter set for one device template."""

    type: DeviceType
    parameters: tuple[tuple[str, object], ...]

    _MORELIA_TYPES: ClassVar[dict[DeviceType, MoreliaType]] = _DEVICE_MORELIA_TYPES

    @classmethod
    def from_dict(cls, type_key: str, values: Mapping[str, object]) -> DeviceSpec:
        '''Return the requirement for the current device'''
        try:
            device_type = DeviceType(type_key)
        except ValueError:
            raise UnknownConfigType("device", type_key) from None

        morelia_type = cls._MORELIA_TYPES.get(device_type)
        if morelia_type is None:
            raise UnsupportedDeviceType(type_key)

        defaulted = dict(values)
        if device_type in _DEFAULT_SAMPLE_RATE_DEVICE_TYPES:
            defaulted.setdefault("sample_rate", _DEFAULT_SAMPLE_RATE)

        coerced = _validate("device", type_key, _load_param_schema(morelia_type), defaulted)
        return cls(type=device_type, parameters=tuple(sorted(coerced.items())))

    def as_dict(self) -> dict[str, object]:
        return dict(self.parameters)


@dataclass(frozen=True, slots=True)
class SinkSpec:
    """Canonical, validated spec for a data sink."""

    type: SinkType
    category: SinkCategory
    parameters: tuple[tuple[str, object], ...]

    _MORELIA_TYPES: ClassVar[dict[SinkType, MoreliaType]] = _SINK_MORELIA_TYPES
    _CATEGORY: ClassVar[dict[SinkType, SinkCategory]] = _SINK_CATEGORY

    @classmethod
    def from_dict(cls, type_key: str, values: Mapping[str, object]) -> SinkSpec:
        try:
            sink_type = SinkType(type_key)
        except ValueError:
            raise UnknownConfigType("sink", type_key) from None

        schema = _load_param_schema(cls._MORELIA_TYPES[sink_type])
        coerced = _validate("sink", type_key, schema, values)
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
    """Return a canonical DeviceSpec validated by its Morelia class schema."""
    return DeviceSpec.from_dict(type_key, parameters)


def lookup_sink(type_key: str, parameters: Mapping[str, object]) -> SinkSpec:
    """Return a canonical SinkSpec validated by its Morelia class schema."""
    return SinkSpec.from_dict(type_key, parameters)


def device_parameter_schema(type_key: str) -> dict[str, list[str]]:
    """Return promptable parameter keys for a supported device type."""
    try:
        device_type = DeviceType(type_key)
    except ValueError:
        raise UnknownConfigType("device", type_key) from None

    morelia_type = _DEVICE_MORELIA_TYPES.get(device_type)
    if morelia_type is None:
        raise UnsupportedDeviceType(type_key)

    schema = _load_param_schema(morelia_type)
    return {
        "required": sorted(schema.required),
        "optional": sorted(schema.optional),
    }


def supported_device_types() -> list[dict[str, object]]:
    """Return dashboard-supported device types and their parameters."""
    supported = []
    for device_type, morelia_type in sorted(
        _DEVICE_MORELIA_TYPES.items(), key=lambda item: item[0].value
    ):
        schema = _load_param_schema(morelia_type)
        supported.append(
            {
                "type": device_type.value,
                "required_parameters": sorted(schema.required),
                "optional_parameters": sorted(schema.optional),
            }
        )
    return supported


def sink_parameter_schema(type_key: str) -> dict[str, object]:
    """Return category and Morelia-owned keys for a supported sink type."""
    try:
        sink_type = SinkType(type_key)
    except ValueError:
        raise UnknownConfigType("sink", type_key) from None

    schema = _load_param_schema(_SINK_MORELIA_TYPES[sink_type])
    return {
        "category": _SINK_CATEGORY[sink_type].value,
        "required": sorted(schema.required),
        "optional": sorted(schema.optional),
    }
