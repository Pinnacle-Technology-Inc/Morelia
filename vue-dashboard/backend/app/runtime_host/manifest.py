"""Immutable runtime manifest — one Dataflow Runtime Host runs one dataflow.

Constructed once at host startup, never changed. The content hash lets the
control plane confirm it is talking to the right host after a daemon restart
without re-reading a manifest file from disk (the file is loaded into a
Manifest object in memory instead).

Schema v2 (packet 06)
---------------------
A device flow no longer carries a single flattened ``{sink_type, sink_location}``
pair. Instead it owns an ordered collection of fully-resolved ``SinkConfig``
descriptors (``DeviceFlow.sinks``), and the manifest carries a durable, nullable
session identity so output segments and recovery gaps can be linked to their
session. The wire form is pure v2 — it never contains ``sink_type`` or
``sink_location`` keys.

Backward compatibility
----------------------
* ``Manifest.from_dict`` still reads persisted **v1** documents
  (``schema_version == "1"``) by translating each ``{sink_type, sink_location}``
  pair into a one-element file ``SinkConfig`` collection. It never re-emits v1:
  the object it returns is a native v2 manifest. Adoption/respawn reuse
  persisted manifests, so v1 reading is release-critical.
* ``DeviceFlow`` still accepts legacy ``sink_type=`` / ``sink_location=``
  construction keywords (translating them to a single file sink) and still
  exposes ``.sink_type`` / ``.sink_location`` read properties. These are a
  compatibility bridge for callers that have not yet migrated to ``.sinks``
  (e.g. ``app/runtime_child/morelia.py``, ``app/services/manifests.py``). A
  later packet migrates those readers/writers to native ``.sinks`` and can then
  drop the bridge.

Secrets / live objects never enter a manifest. Sink parameters are validated
against the sink registry (packet 01) on the way in, which rejects unknown
keys; a dedicated guard additionally rejects raw-secret-looking parameter names
(e.g. an Influx token) — the registry only ever accepts an env-var *name*
(``api_token_env``), never a token value.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import ClassVar

from app.domain.enums import PolicyMode, SinkType

# New manifests are always written at v2. The reader additionally accepts v1
# documents (translating them), but never emits them.
MANIFEST_SCHEMA_VERSION = "2"
_LEGACY_SCHEMA_VERSION = "1"

# Parameter names that would only ever hold a resolved secret value. A manifest
# is secret-free by contract, so these are rejected outright rather than passed
# through — the registry models credentials as an env-var *reference*
# (``api_token_env``), never the value.
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
    """Validate + canonicalize sink parameters through the packet-01 registry.

    Rejects unknown/secret keys and coerces scalars so equal inputs canonicalize
    identically (feeds hash stability). Returns a plain dict. Pure validation —
    it never resolves credentials, allocates paths, or constructs a live sink.
    """
    # Lazy import keeps this module importable without eagerly pulling the
    # services layer, and sidesteps any import-order coupling.
    from app.services.registry import lookup_sink

    spec = lookup_sink(sink_type.value, parameters)
    canonical = spec.as_dict()

    # No live objects/handles: a manifest field must be JSON-serializable.
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
    """One fully-resolved sink descriptor for a source.

    Immutable, JSON-serializable, secret-free, and canonically hashed. ``type``
    is a ``SinkType``; ``parameters`` is the canonical, registry-validated
    parameter map (for file sinks it contains the resolved absolute
    ``file_path``).
    """

    sink_id: str
    name: str
    type: SinkType
    parameters: dict[str, object]

    _REQUIRED: ClassVar[frozenset[str]] = frozenset({"sink_id", "name", "type", "parameters"})

    def __hash__(self) -> int:
        # dict field prevents the frozen-dataclass auto __hash__; derive from the
        # canonical wire form so equal content = equal hash regardless of dict
        # construction order.
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
        # Bypass the frozen guard — standard pattern for a computed/normalized
        # field on a frozen dataclass; __post_init__ runs inside __init__.
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


def _sink_from_v1(device_id: str, sink_type: object, sink_location: object) -> SinkConfig:
    """Translate a v1 ``{sink_type, sink_location}`` pair to one file SinkConfig.

    v1 only ever modeled file-category sinks with a path. A non-file sink type
    has no ``file_path`` slot in the registry, so the registry rejects the
    translation with a clear error rather than mis-modeling it.
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
    """One device, its hardware binding, snapshotted parameters, and ordered sinks.

    v2 owns ``sinks: tuple[SinkConfig, ...]`` (at least one, with per-source
    unique sink IDs and names). A legacy ``sink_type`` + ``sink_location`` pair
    may still be supplied at construction — it is translated to a single file
    sink — and ``.sink_type`` / ``.sink_location`` remain available as read
    properties for callers not yet migrated to ``.sinks``.
    """

    device_id: str
    name: str
    nickname: str | None
    hardware_id: str
    port: str
    parameters: dict[str, object]
    sinks: tuple[SinkConfig, ...]

    _V2_KNOWN: ClassVar[frozenset[str]] = frozenset(
        {"device_id", "name", "nickname", "hardware_id", "port", "parameters", "sinks"}
    )
    _V2_REQUIRED: ClassVar[frozenset[str]] = frozenset(
        {"device_id", "name", "hardware_id", "port", "parameters", "sinks"}
    )
    _V1_KNOWN: ClassVar[frozenset[str]] = frozenset(
        {
            "device_id",
            "name",
            "nickname",
            "hardware_id",
            "port",
            "parameters",
            "sink_type",
            "sink_location",
        }
    )
    _V1_REQUIRED: ClassVar[frozenset[str]] = frozenset(
        {"device_id", "name", "hardware_id", "port", "parameters", "sink_type", "sink_location"}
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
    ) -> None:
        object.__setattr__(self, "device_id", device_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "nickname", nickname)
        object.__setattr__(self, "hardware_id", hardware_id)
        object.__setattr__(self, "port", port)
        object.__setattr__(self, "parameters", dict(parameters) if isinstance(parameters, Mapping) else parameters)

        if sinks is not None:
            if sink_type is not None or sink_location is not None:
                raise ValueError(
                    "device flow cannot mix v2 'sinks' with legacy 'sink_type'/'sink_location'"
                )
            resolved_sinks = tuple(sinks)
        else:
            if sink_type is None or sink_location is None:
                raise ValueError(
                    "device flow requires 'sinks' (or legacy 'sink_type' + 'sink_location')"
                )
            resolved_sinks = (_sink_from_v1(device_id, sink_type, sink_location),)

        object.__setattr__(self, "sinks", resolved_sinks)
        self._validate()

    def __hash__(self) -> int:
        return hash(json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")))

    # -- compatibility bridge: single-sink read accessors ---------------------
    @property
    def sink_type(self) -> SinkType:
        """First sink's type. Bridge for pre-v2 readers (one sink per flow)."""
        return self.sinks[0].type

    @property
    def sink_location(self) -> str | None:
        """First sink's resolved file path, if any. Bridge for pre-v2 readers."""
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
        return {
            "device_id": self.device_id,
            "name": self.name,
            "nickname": self.nickname,
            "hardware_id": self.hardware_id,
            "port": self.port,
            "parameters": self.parameters,
            "sinks": [sink.to_dict() for sink in self.sinks],
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> DeviceFlow:
        keys = set(values)
        has_v2 = "sinks" in keys
        has_v1 = "sink_type" in keys or "sink_location" in keys
        if has_v2 and has_v1:
            raise ValueError(
                "device flow cannot mix v2 'sinks' with legacy 'sink_type'/'sink_location'"
            )

        if has_v2:
            unknown = keys - cls._V2_KNOWN
            if unknown:
                raise ValueError(f"unknown device flow fields: {', '.join(sorted(unknown))}")
            missing = cls._V2_REQUIRED - keys
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
            )

        # v1 translation path
        unknown = keys - cls._V1_KNOWN
        if unknown:
            raise ValueError(f"unknown device flow fields: {', '.join(sorted(unknown))}")
        missing = cls._V1_REQUIRED - keys
        if missing:
            raise ValueError(f"missing device flow fields: {', '.join(sorted(missing))}")

        params_raw = values["parameters"]
        if not isinstance(params_raw, Mapping):
            raise ValueError("parameters must be a mapping")

        return cls(
            device_id=values["device_id"],  # type: ignore[arg-type]
            name=values["name"],  # type: ignore[arg-type]
            nickname=values.get("nickname"),  # type: ignore[arg-type]
            hardware_id=values["hardware_id"],  # type: ignore[arg-type]
            port=values["port"],  # type: ignore[arg-type]
            parameters=dict(params_raw),
            sink_type=values["sink_type"],
            sink_location=values["sink_location"],
        )


def _content_hash(
    schema_version: str,
    dataflow_id: str,
    session_id: int | None,
    device_flows: tuple[DeviceFlow, ...],
    policy: PolicyMode,
) -> str:
    """SHA-256 of the canonical JSON of the manifest's stable fields (no hash field).

    ``sort_keys`` canonicalizes dict *key* order but preserves list order, so
    the ordered sink and device-flow collections stay significant while
    incidental dict construction order does not affect the hash.
    """
    payload = {
        "schema_version": schema_version,
        "dataflow_id": dataflow_id,
        "session_id": session_id,
        "policy": policy.value,
        "device_flows": [df.to_dict() for df in device_flows],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _v1_stored_hash(values: Mapping[str, object]) -> str:
    """Recompute the original v1 content hash from a raw v1 wire document.

    Used to preserve strict stored-hash validation when reading (and
    translating) a persisted v1 manifest: the integrity check runs against the
    v1 payload the v1 writer hashed, even though the object we return is v2.
    """
    payload = {
        "schema_version": values["schema_version"],
        "dataflow_id": values["dataflow_id"],
        "policy": values["policy"],
        "device_flows": values["device_flows"],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Manifest:
    """A frozen description of one Dataflow Runtime Host's dataflow and device→sink topology.

    ``schema_version`` gates incompatible wire-format changes.
    ``session_id`` is the durable session identity used to associate output
    segments and recovery gaps with their session; it is ``None`` for
    side-effect-free previews and required (populated by the resolver) for
    persisted runtime manifests.
    ``hash`` is the unique ID to identify the host and dataflow relationship;
    it covers the entire ordered sink collection and the session identity.
    """

    schema_version: str
    dataflow_id: str
    policy: PolicyMode
    device_flows: tuple[DeviceFlow, ...]
    session_id: int | None = None
    hash: str = field(init=False)

    _V2_KNOWN: ClassVar[frozenset[str]] = frozenset(
        {"schema_version", "dataflow_id", "policy", "device_flows", "session_id", "hash"}
    )
    _V2_REQUIRED: ClassVar[frozenset[str]] = frozenset(
        {"schema_version", "dataflow_id", "policy", "device_flows"}
    )
    _V1_KNOWN: ClassVar[frozenset[str]] = frozenset(
        {"schema_version", "dataflow_id", "policy", "device_flows", "hash"}
    )
    _V1_REQUIRED: ClassVar[frozenset[str]] = frozenset(
        {"schema_version", "dataflow_id", "policy", "device_flows"}
    )

    def __hash__(self) -> int:
        return hash(self.hash)

    def __post_init__(self) -> None:
        if not isinstance(self.schema_version, str) or not self.schema_version:
            raise ValueError("schema_version must be a non-empty string")
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

        # Globally-unique file locations across every sink of every device.
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

        # Bypass the frozen guard — this is the standard pattern for computed
        # fields on frozen dataclasses; __post_init__ runs inside __init__.
        object.__setattr__(
            self,
            "hash",
            _content_hash(
                self.schema_version,
                self.dataflow_id,
                self.session_id,
                self.device_flows,
                self.policy,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "dataflow_id": self.dataflow_id,
            "policy": self.policy.value,
            "session_id": self.session_id,
            "device_flows": [df.to_dict() for df in self.device_flows],
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> Manifest:
        schema_version = values.get("schema_version")
        if schema_version == MANIFEST_SCHEMA_VERSION:
            return cls._from_v2(values)
        if schema_version == _LEGACY_SCHEMA_VERSION:
            return cls._from_v1(values)
        raise ValueError(f"unsupported manifest schema version: {schema_version!r}")

    @classmethod
    def _from_v2(cls, values: Mapping[str, object]) -> Manifest:
        unknown = set(values) - cls._V2_KNOWN
        if unknown:
            raise ValueError(f"unknown manifest fields: {', '.join(sorted(unknown))}")
        missing = cls._V2_REQUIRED - set(values)
        if missing:
            raise ValueError(f"missing manifest fields: {', '.join(sorted(missing))}")

        policy = cls._resolve_policy(values["policy"])
        device_flows_raw = values["device_flows"]
        if not isinstance(device_flows_raw, (list, tuple)):
            raise ValueError("device_flows must be a list")

        manifest = cls(
            schema_version=MANIFEST_SCHEMA_VERSION,
            dataflow_id=values["dataflow_id"],  # type: ignore[arg-type]
            policy=policy,
            device_flows=tuple(DeviceFlow.from_dict(df) for df in device_flows_raw),  # type: ignore[arg-type]
            session_id=values.get("session_id"),  # type: ignore[arg-type]
        )

        stored_hash = values.get("hash")
        if stored_hash is not None and stored_hash != manifest.hash:
            raise ValueError("manifest hash mismatch — content may have been tampered with")
        return manifest

    @classmethod
    def _from_v1(cls, values: Mapping[str, object]) -> Manifest:
        unknown = set(values) - cls._V1_KNOWN
        if unknown:
            raise ValueError(f"unknown manifest fields: {', '.join(sorted(unknown))}")
        missing = cls._V1_REQUIRED - set(values)
        if missing:
            raise ValueError(f"missing manifest fields: {', '.join(sorted(missing))}")

        # Validate the stored hash against the *v1* payload before translating —
        # strict integrity check on the document as it was written.
        stored_hash = values.get("hash")
        if stored_hash is not None and stored_hash != _v1_stored_hash(values):
            raise ValueError("manifest hash mismatch — content may have been tampered with")

        policy = cls._resolve_policy(values["policy"])
        device_flows_raw = values["device_flows"]
        if not isinstance(device_flows_raw, (list, tuple)):
            raise ValueError("device_flows must be a list")

        # Emit v2, never v1: the translated flows carry one file SinkConfig each
        # and the manifest is stamped at the current (v2) schema version.
        return cls(
            schema_version=MANIFEST_SCHEMA_VERSION,
            dataflow_id=values["dataflow_id"],  # type: ignore[arg-type]
            policy=policy,
            device_flows=tuple(DeviceFlow.from_dict(df) for df in device_flows_raw),  # type: ignore[arg-type]
            session_id=None,
        )

    @staticmethod
    def _resolve_policy(policy_raw: object) -> PolicyMode:
        try:
            return PolicyMode(policy_raw)
        except ValueError:
            raise ValueError(f"unknown policy mode: {policy_raw!r}") from None
