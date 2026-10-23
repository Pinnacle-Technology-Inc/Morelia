"""Saved configuration for one dataflow and its ordered device and sink settings.

The control plane uses the content hash to match a runtime to its saved
configuration after a restart. Credentials are referenced by environment
variable name, such as ``api_token_env``.

Only schema v3 is supported. It stores ordered sinks, an optional session ID,
duration, and resolved device connections.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from app.domain.duration import validate_duration_seconds
from app.domain.enums import PolicyMode, SinkType

MANIFEST_SCHEMA_VERSION = "3"

# Reject credential values so saved manifests contain only credential references.
_RAW_SECRET_PARAM_KEYS = frozenset(
    {
        "api_token",
        "apitoken",
        "api_key",
        "apikey",
        "token",
        "password",
        "passwd",
        "secret",
        "access_token",
        "auth_token",
    }
)


def _reject_secret_params(parameters: Mapping[str, object], sink_id: str) -> None:
    for key in parameters:
        if isinstance(key, str) and key.lower() in _RAW_SECRET_PARAM_KEYS:
            raise ValueError(
                f"sink {sink_id!r} parameter {key!r} looks like a raw secret value; "
                "manifests are secret-free — reference a credential by env-var name "
                "(e.g. 'api_token_env') instead"
            )


def _canonical_sink_parameters(
    sink_type: SinkType, parameters: Mapping[str, object]
) -> dict[str, object]:
    """Normalize validated sink parameters so equivalent settings hash alike.

    Validation does not resolve credentials, allocate paths, or open a sink.
    """
    # Defer loading the services layer until parameters need validation.
    from app.services.registry import lookup_sink

    spec = lookup_sink(sink_type.value, parameters)
    canonical = spec.as_dict()

    # Saved manifests must serialize without live objects or handles.
    try:
        json.dumps(canonical, separators=(",", ":"))
    except (TypeError, ValueError):
        raise ValueError(
            f"sink parameters for {sink_type.value!r} are not JSON-serializable "
            "(a live object or handle may have leaked into the manifest)"
        ) from None
    return canonical


@dataclass(frozen=True, slots=True)
class SinkConfig:
    """Sink identity and validated settings for one source.

    File sinks use ``file_path``; credential settings use environment variable names.
    """

    sink_id: str
    name: str
    type: SinkType
    parameters: dict[str, object]

    _REQUIRED: ClassVar[frozenset[str]] = frozenset({"sink_id", "name", "type", "parameters"})

    def __hash__(self) -> int:
        # Parameter insertion order must not change the hash of equivalent settings.
        return hash(json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")))

    def __post_init__(self) -> None:
        if not isinstance(self.sink_id, str) or not self.sink_id:
            raise ValueError("sink_id must be a non-empty string")
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("sink name must be a non-empty string")
        if not isinstance(self.type, SinkType):
            raise ValueError("sink type must be a SinkType")
        if not isinstance(self.parameters, Mapping):
            raise ValueError("sink parameters must be a mapping")

        _reject_secret_params(self.parameters, self.sink_id)
        canonical = _canonical_sink_parameters(self.type, self.parameters)
        object.__setattr__(self, "parameters", canonical)

    def to_dict(self) -> dict[str, object]:
        return {
            "sink_id": self.sink_id,
            "name": self.name,
            "type": self.type.value,
            "parameters": dict(self.parameters),
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> SinkConfig:
        unknown = set(values) - cls._REQUIRED
        if unknown:
            raise ValueError(f"unknown sink fields: {', '.join(sorted(unknown))}")
        missing = cls._REQUIRED - set(values)
        if missing:
            raise ValueError(f"missing sink fields: {', '.join(sorted(missing))}")

        params_raw = values["parameters"]
        if not isinstance(params_raw, Mapping):
            raise ValueError("sink parameters must be a mapping")

        type_raw = values["type"]
        try:
            sink_type = SinkType(type_raw)
        except ValueError:
            raise ValueError(f"unknown sink type: {type_raw!r}") from None

        return cls(
            sink_id=values["sink_id"],  # type: ignore[arg-type]
            name=values["name"],  # type: ignore[arg-type]
            type=sink_type,
            parameters=dict(params_raw),
        )


def _single_file_sink(device_id: str, sink_type: object, sink_location: object) -> SinkConfig:
    """Read legacy file-sink settings as a single sink.

    The registry rejects sink types that do not accept ``file_path``.
    """
    if isinstance(sink_type, SinkType):
        resolved_type = sink_type
    else:
        try:
            resolved_type = SinkType(sink_type)
        except ValueError:
            raise ValueError(f"unknown sink_type: {sink_type!r}") from None

    if not isinstance(sink_location, str) or not sink_location:
        raise ValueError("sink_location must be a non-empty string")

    return SinkConfig(
        sink_id=f"{device_id}:{resolved_type.value}",
        name=resolved_type.value,
        type=resolved_type,
        parameters={"file_path": sink_location},
    )


@dataclass(frozen=True, slots=True, init=False)
class DeviceFlow:
    """Device identity, saved parameters, and at least one ordered sink.

    Sink IDs and names must be unique within the device. Legacy callers may
    supply ``sink_type`` and ``sink_location`` to configure one file sink.
    """

    device_id: str
    name: str
    nickname: str | None
    hardware_id: str
    port: str
    parameters: dict[str, object]
    sinks: tuple[SinkConfig, ...]
    connection: dict[str, object] | None

    _KNOWN: ClassVar[frozenset[str]] = frozenset(
        {"device_id", "name", "nickname", "hardware_id", "port", "parameters", "sinks", "connection"}
    )
    _REQUIRED: ClassVar[frozenset[str]] = frozenset(
        {"device_id", "name", "hardware_id", "port", "parameters", "sinks"}
    )
    def __init__(
        self,
        *,
        device_id: str,
        name: str,
        nickname: str | None = None,
        hardware_id: str,
        port: str,
        parameters: Mapping[str, object],
        sinks: tuple[SinkConfig, ...] | list[SinkConfig] | None = None,
        sink_type: object = None,
        sink_location: object = None,
        connection: Mapping[str, object] | None = None,
    ) -> None:
        object.__setattr__(self, "device_id", device_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "nickname", nickname)
        object.__setattr__(self, "hardware_id", hardware_id)
        object.__setattr__(self, "port", port)
        object.__setattr__(self, "parameters", dict(parameters) if isinstance(parameters, Mapping) else parameters)
        from app.domain.connections import normalize_resolved_connection
        object.__setattr__(self, "connection", normalize_resolved_connection(connection, hardware_id=hardware_id)
                           if connection is not None else None)

        if sinks is not None:
            if sink_type is not None or sink_location is not None:
                raise ValueError(
                    "device flow cannot mix 'sinks' with legacy 'sink_type'/'sink_location'"
                )
            resolved_sinks = tuple(sinks)
        else:
            if sink_type is None or sink_location is None:
                raise ValueError(
                    "device flow requires 'sinks' (or legacy 'sink_type' + 'sink_location')"
                )
            resolved_sinks = (_single_file_sink(device_id, sink_type, sink_location),)

        object.__setattr__(self, "sinks", resolved_sinks)
        self._validate()

    def __hash__(self) -> int:
        return hash(json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")))

    @property
    def sink_type(self) -> SinkType:
        """Expose the first sink's type for legacy single-sink callers."""
        return self.sinks[0].type

    @property
    def sink_location(self) -> str | None:
        """Expose the first sink's file path, if any, for legacy callers."""
        return self.sinks[0].parameters.get("file_path")  # type: ignore[return-value]

    def _validate(self) -> None:
        if not isinstance(self.device_id, str) or not self.device_id:
            raise ValueError("device_id must be a non-empty string")
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("name must be a non-empty string")
        if self.nickname is not None and not isinstance(self.nickname, str):
            raise ValueError("nickname must be a string or None")
        if not isinstance(self.hardware_id, str) or not self.hardware_id:
            raise ValueError("hardware_id must be a non-empty string")
        if not isinstance(self.port, str) or not self.port:
            raise ValueError("port must be a non-empty string")
        if not isinstance(self.parameters, dict):
            raise ValueError("parameters must be a dict")
        if not self.sinks:
            raise ValueError("device flow must contain at least one sink")
        for sink in self.sinks:
            if not isinstance(sink, SinkConfig):
                raise ValueError("each sink must be a SinkConfig")

        seen_ids: set[str] = set()
        seen_names: set[str] = set()
        for sink in self.sinks:
            if sink.sink_id in seen_ids:
                raise ValueError(f"duplicate sink_id in device flow: {sink.sink_id!r}")
            seen_ids.add(sink.sink_id)
            if sink.name in seen_names:
                raise ValueError(f"duplicate sink name in device flow: {sink.name!r}")
            seen_names.add(sink.name)

    def to_dict(self) -> dict[str, object]:
        payload = {
            "device_id": self.device_id,
            "name": self.name,
            "nickname": self.nickname,
            "hardware_id": self.hardware_id,
            "port": self.port,
            "parameters": self.parameters,
            "sinks": [sink.to_dict() for sink in self.sinks],
        }
        if self.connection is not None:
            payload["connection"] = dict(self.connection)
        return payload

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> DeviceFlow:
        keys = set(values)
        unknown = keys - cls._KNOWN
        if unknown:
            raise ValueError(f"unknown device flow fields: {', '.join(sorted(unknown))}")
        missing = cls._REQUIRED - keys
        if missing:
            raise ValueError(f"missing device flow fields: {', '.join(sorted(missing))}")

        params_raw = values["parameters"]
        if not isinstance(params_raw, Mapping):
            raise ValueError("parameters must be a mapping")
        sinks_raw = values["sinks"]
        if not isinstance(sinks_raw, (list, tuple)):
            raise ValueError("sinks must be a list")

        return cls(
            device_id=values["device_id"],  # type: ignore[arg-type]
            name=values["name"],  # type: ignore[arg-type]
            nickname=values.get("nickname"),  # type: ignore[arg-type]
            hardware_id=values["hardware_id"],  # type: ignore[arg-type]
            port=values["port"],  # type: ignore[arg-type]
            parameters=dict(params_raw),
            sinks=tuple(SinkConfig.from_dict(s) for s in sinks_raw),  # type: ignore[arg-type]
            connection=values.get("connection"),
        )


def _content_hash(
    schema_version: str,
    dataflow_id: str,
    session_id: int | None,
    device_flows: tuple[DeviceFlow, ...],
    policy: PolicyMode,
    duration_seconds: int | None = None,
) -> str:
    """Hash the saved settings, excluding the hash field itself.

    Device and sink order affect the hash; dictionary key order does not.
    """
    payload = {
        "schema_version": schema_version,
        "dataflow_id": dataflow_id,
        "session_id": session_id,
        "policy": policy.value,
        "device_flows": [df.to_dict() for df in device_flows],
    }
    payload["duration_seconds"] = duration_seconds
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Manifest:
    """Saved settings used to launch or recover one dataflow.

    ``session_id`` links output segments and recovery gaps to a session; previews
    omit it. ``hash`` identifies the configuration, including device and sink
    order, session ID, and duration.
    """

    schema_version: str
    dataflow_id: str
    policy: PolicyMode
    device_flows: tuple[DeviceFlow, ...]
    session_id: int | None = None
    duration_seconds: int | None = None
    hash: str = field(init=False)

    _KNOWN: ClassVar[frozenset[str]] = frozenset(
        {"schema_version", "dataflow_id", "policy", "device_flows", "session_id", "duration_seconds", "hash"}
    )
    _REQUIRED: ClassVar[frozenset[str]] = frozenset(
        {"schema_version", "dataflow_id", "policy", "device_flows"}
    )

    def __hash__(self) -> int:
        return hash(self.hash)

    def __post_init__(self) -> None:
        if not isinstance(self.schema_version, str) or not self.schema_version:
            raise ValueError("schema_version must be a non-empty string")
        if self.schema_version != MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported manifest schema version")
        if self.duration_seconds is not None:
            # Keep saved manifests readable regardless of today's date.
            # The runtime checks the deadline against the first sample's arrival time.
            validate_duration_seconds(self.duration_seconds, start_at=datetime.min.replace(tzinfo=UTC))
        if not isinstance(self.dataflow_id, str) or not self.dataflow_id:
            raise ValueError("dataflow_id must be a non-empty string")
        if not isinstance(self.policy, PolicyMode):
            raise ValueError("policy must be a PolicyMode")
        if self.session_id is not None and (
            isinstance(self.session_id, bool) or not isinstance(self.session_id, int)
        ):
            raise ValueError("session_id must be an int or None")
        if not self.device_flows:
            raise ValueError("manifest must contain at least one device flow")

        seen_devices: set[str] = set()
        for df in self.device_flows:
            if df.device_id in seen_devices:
                raise ValueError(f"duplicate device_id in manifest: {df.device_id!r}")
            seen_devices.add(df.device_id)

        # Two sinks must not write to the same file, even on different devices.
        seen_locations: set[str] = set()
        for df in self.device_flows:
            for sink in df.sinks:
                location = sink.parameters.get("file_path")
                if location is None:
                    continue
                if location in seen_locations:
                    raise ValueError(
                        f"sink location {location!r} is claimed by more than one sink"
                    )
                seen_locations.add(location)  # type: ignore[arg-type]

        object.__setattr__(
            self,
            "hash",
            _content_hash(
                self.schema_version,
                self.dataflow_id,
                self.session_id,
                self.device_flows,
                self.policy,
                self.duration_seconds,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        payload = {
            "schema_version": self.schema_version,
            "dataflow_id": self.dataflow_id,
            "policy": self.policy.value,
            "session_id": self.session_id,
            "device_flows": [df.to_dict() for df in self.device_flows],
            "hash": self.hash,
        }
        payload["duration_seconds"] = self.duration_seconds
        return payload

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> Manifest:
        schema_version = values.get("schema_version")
        if schema_version != MANIFEST_SCHEMA_VERSION:
            raise ValueError(f"unsupported manifest schema version: {schema_version!r}")
        unknown = set(values) - cls._KNOWN
        if unknown:
            raise ValueError(f"unknown manifest fields: {', '.join(sorted(unknown))}")
        missing = cls._REQUIRED - set(values)
        if missing:
            raise ValueError(f"missing manifest fields: {', '.join(sorted(missing))}")

        policy = cls._resolve_policy(values["policy"])
        device_flows_raw = values["device_flows"]
        if not isinstance(device_flows_raw, (list, tuple)):
            raise ValueError("device_flows must be a list")

        manifest = cls(
            schema_version=values["schema_version"],
            dataflow_id=values["dataflow_id"],  # type: ignore[arg-type]
            policy=policy,
            device_flows=tuple(DeviceFlow.from_dict(df) for df in device_flows_raw),  # type: ignore[arg-type]
            session_id=values.get("session_id"),  # type: ignore[arg-type]
            duration_seconds=values.get("duration_seconds"),
        )

        stored_hash = values.get("hash")
        if stored_hash is not None and stored_hash != manifest.hash:
            raise ValueError("manifest hash mismatch — content may have been tampered with")
        return manifest

    @staticmethod
    def _resolve_policy(policy_raw: object) -> PolicyMode:
        try:
            return PolicyMode(policy_raw)
        except ValueError:
            raise ValueError(f"unknown policy mode: {policy_raw!r}") from None
