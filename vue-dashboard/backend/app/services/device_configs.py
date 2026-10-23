"""Port-bound device config service.

A *device config* is one physical device made runnable: ``device_type`` +
``hardware_id`` (its unique identity), a ``port`` attribute, a snapshot of
``parameters``, an optional ``nickname``, and optional ``source_template``
provenance. Configs move between ``FREE`` and ``CLAIMED`` as sessions attach and
detach. Parameters are validated through the typed registry, exactly like the
device-template library.

Mirrors ``app.services.device_templates`` in shape: module-level functions, a
module ``_repository``, and ``with transaction():`` for mutations. No Flask, no
HTTP — adapters map the typed errors below at their boundary.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, inspect, or_

from app.database import db, transaction
from app.domain.connections import validate_device_connection
from app.domain.enums import (
    DeviceClaimState, DeviceType, RuntimeOwnershipState, SessionStatus, WatchdogProcessState,
)
from app.domain.errors import (
    DeviceClaimConflict,
    DeviceConfigExists,
    DeviceConfigNotFound,
    DeviceConfigNotFree,
    DeviceTemplateNotFound,
    InvalidHardwareId,
)
from app.models.device_config import DeviceConfig
from app.models.device_template import DeviceTemplate
from app.models.runtime_ownership import RuntimeOwnership
from app.models.session import Session
from app.repositories.device_configs import DeviceConfigRepository
from app.services import device_registrations, device_templates
from app.services.registry import lookup_device

_repository = DeviceConfigRepository()

STARTING_CLAIM_LEASE_SECONDS = 120

# Plan decision C ("Physical identity", resolved 2026-07-02): hardware_id
# mirrors the reported FTDI serial verbatim, matched case-sensitively and
# exactly (no case-folding).
#
# Packet 10 ("hardware-id validation contract", resolved 2026-07-30): the legal
# value is 1-8 ASCII alphanumeric characters. Leading zeros and letter case are
# significant, so the value stays a string and is never normalized or coerced.
_HARDWARE_ID_PATTERN = re.compile(r"^[0-9a-zA-Z]{1,10}$")


def _canonical_parameters(device_type: DeviceType, raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate params for *device_type* through the registry, return canonical dict."""
    # Accept either an enum member or the raw string SQLAlchemy may hand back.
    type_key = DeviceType(device_type).value
    spec = lookup_device(type_key, raw or {})
    return spec.as_dict()


def create(
    *,
    device_type: DeviceType,
    hardware_id: str,
    port: str | None = None,
    parameters: Mapping[str, Any] | None = None,
    connection: Mapping[str, Any] | None = None,
    nickname: str | None = None,
    source_template: str | None = None,
    source_template_hash: str | None = None,
) -> DeviceConfig:
    """Persist a new port-bound device config after validating its parameters.

    Identity is ``device_type + hardware_id`` and must be unique; a duplicate
    raises ``DeviceConfigExists`` rather than surfacing a raw IntegrityError.

    ``hardware_id`` must be 1-8 ASCII alphanumeric characters; anything else
    raises ``InvalidHardwareId`` before the duplicate-identity check runs.
    """
    if not _HARDWARE_ID_PATTERN.fullmatch(hardware_id):
        raise InvalidHardwareId(hardware_id)

    device_registrations.ensure_nickname_available(
        device_type=device_type,
        hardware_id=hardware_id,
        nickname=nickname,
    )

    if _repository.get_by_identity(device_type, hardware_id) is not None:
        raise DeviceConfigExists(device_type.value, hardware_id)

    canonical = _canonical_parameters(device_type, parameters)
    canonical_connection = validate_device_connection(device_type, connection)
    # The address is only a cached observation. Run startup resolves identity.
    address = hardware_id if canonical_connection["preference"] == "d2xx" else (port or hardware_id)
    row = _repository.create(
        device_type=device_type,
        hardware_id=hardware_id,
        port=address,
        parameters=canonical,
        connection=canonical_connection,
        nickname=nickname,
        source_template=source_template,
        source_template_hash=source_template_hash,
    )
    device_registrations.bind_config(row)
    return row


def create_from_template(
    template: DeviceTemplate,
    *,
    hardware_id: str,
    port: str | None = None,
    connection: Mapping[str, Any] | None = None,
    nickname: str | None = None,
) -> DeviceConfig:
    """Build a config by snapshot-copying *template*'s params.

    The params are copied by value, so later edits to the template never change
    this config. ``source_template`` records the provenance label.
    """
    return create(
        device_type=DeviceType(template.content["type"]),
        hardware_id=hardware_id,
        port=port,
        parameters=template.content.get("parameters", {}),
        connection=connection,
        nickname=nickname,
        source_template=template.file_path,
        source_template_hash=template.content_hash,
    )


def get_by_id(config_id: int) -> DeviceConfig | None:
    """Return a device config by primary key, or None."""
    return _repository.get(config_id)


def rename(
    *,
    device_type: DeviceType,
    hardware_id: str,
    nickname: str,
) -> DeviceConfig:
    """Assign the stable operator-facing name for a physical device config."""
    if not _HARDWARE_ID_PATTERN.fullmatch(hardware_id):
        raise InvalidHardwareId(hardware_id)
    normalized_nickname = nickname.strip()
    if not normalized_nickname:
        raise ValueError("device name is required")

    row = _repository.get_by_identity(device_type, hardware_id)
    if row is None:
        raise DeviceConfigNotFound(f"{device_type.value}:{hardware_id}")

    with transaction():
        row.nickname = normalized_nickname
    device_registrations.register(
        device_type=device_type,
        hardware_id=hardware_id,
        nickname=normalized_nickname,
    )
    return row


def list() -> list[DeviceConfig]:  # noqa: A001 - public API named to match device_templates
    """Return all device configs ordered by type then hardware id."""
    return _repository.list()


def find_by_hardware_id(hardware_id: str) -> list[DeviceConfig]:
    """Return every config that shares *hardware_id* (across device types)."""
    return _repository.find_by_hardware_id(hardware_id)


def _require(config_id: int) -> DeviceConfig:
    row = _repository.get(config_id)
    if row is None:
        raise DeviceConfigNotFound(config_id)
    return row


def _resolve_template(reference: str, device_type: DeviceType) -> DeviceTemplate:
    """Resolve a relink target by ``file_path`` first, then by portable name.

    Session templates store the ``device-templates/foo.toml`` form while the
    CLI's portable form is the bare name, and both reach this service.
    """
    try:
        template = device_templates.get_by_path(reference)
    except DeviceTemplateNotFound:
        template = None
    if template is None:
        template = device_templates.get_by_name(reference)
    if template is None:
        raise DeviceTemplateNotFound(reference)
    # A cross-type link would claim provenance the parameters can never satisfy:
    # they are validated against the *config's* type, not the template's.
    if template.type != DeviceType(device_type).value:
        raise ValueError(
            f"device template {template.name!r} is for {template.type}, "
            f"not {DeviceType(device_type).value}"
        )
    return template


def edit(
    config_id: int,
    *,
    parameters: Mapping[str, Any] | None = None,
    update_source_template: bool = False,
    source_template: str | None = None,
    connection: Mapping[str, Any] | None = None,
) -> DeviceConfig:
    """Rewrite a config's parameters. Allowed only while the config is FREE.

    Editing a claimed device would desync a running manifest, so this raises
    ``DeviceConfigNotFree`` when the config is CLAIMED.

    Provenance (Option C — a dedicated history column):
      • update_source_template=True  → also rewrite the linked template's content
        and KEEP the live ``source_template`` link.
      • source_template=<path|name>  → relink to that template WITHOUT touching
        its content, preserving any previous link in ``source_template_history``.
        This is the "adopt a template's settings" direction: the template is
        authoritative and the config is brought into line with it.
      • neither → the config becomes "custom": the live link is severed and its
        old value is preserved in ``source_template_history``.

    The first two are mutually exclusive — they disagree about which side is the
    source of truth, so accepting both would make the outcome order-dependent.

    ``source_template_hash`` records the template revision the link was made
    against, exactly as ``create_from_template`` does. Callers relinking are
    responsible for passing parameters that actually match that template;
    nothing here forces them to agree, because a relink is also how an operator
    records "these settings came from here" for a hand-tuned config.
    """
    if update_source_template and source_template is not None:
        raise ValueError(
            "update_source_template and source_template are mutually exclusive"
        )

    row = _require(config_id)
    if row.claim_state is not DeviceClaimState.FREE:
        raise DeviceConfigNotFree(config_id)

    canonical_connection = (
        validate_device_connection(row.device_type, connection) if connection is not None else None
    )
    if parameters is None:
        if update_source_template or source_template is not None:
            raise ValueError("parameters are required when changing template provenance")
        if canonical_connection is None:
            raise ValueError("provide parameters or connection to edit a device config")
        with transaction():
            row.connection = canonical_connection
            if canonical_connection["preference"] == "d2xx":
                row.port = row.hardware_id
        return row

    canonical = _canonical_parameters(row.device_type, parameters)

    # Resolve before opening the transaction so an unknown template aborts the
    # edit outright rather than leaving the parameters rewritten but unlinked.
    relink_target = (
        _resolve_template(source_template, row.device_type) if source_template is not None else None
    )

    with transaction():
        # Set params first so the nested template write below commits both the
        # config row and the template in one flush (keeps the branch atomic).
        row.parameters = canonical
        if canonical_connection is not None:
            row.connection = canonical_connection
            if canonical_connection["preference"] == "d2xx":
                row.port = row.hardware_id
        if relink_target is not None:
            if row.source_template is not None and row.source_template != relink_target.file_path:
                row.source_template_history = row.source_template
            row.source_template = relink_target.file_path
            row.source_template_hash = relink_target.content_hash
        elif update_source_template:
            if row.source_template is not None:
                # Push the edited params back into the (mutable) library template.
                template = device_templates.get_by_path(row.source_template)
                if template is None:
                    raise ValueError(f"source device template not found: {row.source_template}")
                updated_template = device_templates.update(
                    template.name,
                    {"type": DeviceType(row.device_type).value, "parameters": canonical},
                )
                row.source_template_hash = updated_template.content_hash
        elif row.source_template is not None:
            # Diverged from its template: sever the live link, keep the breadcrumb.
            row.source_template_history = row.source_template
            row.source_template = None
            row.source_template_hash = None

    return row


def delete(config_id: int) -> None:
    """Delete a config. Allowed only while FREE."""
    row = _require(config_id)
    if row.claim_state is not DeviceClaimState.FREE:
        raise DeviceConfigNotFree(config_id)
    _repository.delete(row)


def _release_is_safe():
    """SQL proof checked in the same statement that relinquishes ownership.

    A deadline is only eligibility for cleanup. Launch intent, a command in
    flight, and unresolved process ownership continue to fence the hardware.
    Historical STOPPED rows are not proof: require a positive receipt,
    identity-matching administrative evidence, or a proven failed launch.
    """
    administrative = RuntimeOwnership.details["administrative_stop_evidence"]
    teardown_proven = or_(
        and_(
            RuntimeOwnership.watchdog_id.is_not(None),
            RuntimeOwnership.watchdog_exit_details["teardown_confirmed"].as_boolean().is_(True),
        ),
        and_(
            administrative["runtime_id"].as_string() == RuntimeOwnership.runtime_id,
            administrative["watchdog_id"].as_string().is_not_distinct_from(RuntimeOwnership.watchdog_id),
            administrative["dataflow_id"].as_string() == RuntimeOwnership.dataflow_id,
            administrative["manifest_hash"].as_string() == RuntimeOwnership.manifest_hash,
            administrative["payload"]["teardown_confirmed"].as_boolean().is_(True),
        ),
        and_(
            RuntimeOwnership.details["host_launch_failed"].as_boolean().is_(True),
            RuntimeOwnership.pid.is_(None),
            RuntimeOwnership.watchdog_id.is_(None),
            RuntimeOwnership.watchdog_pid.is_(None),
        ),
    )
    unresolved_runtime = db.select(RuntimeOwnership.id).where(
        RuntimeOwnership.session_id == DeviceConfig.claimed_session_id,
        or_(
            RuntimeOwnership.state != RuntimeOwnershipState.STOPPED,
            RuntimeOwnership.stopped_at.is_(None),
            teardown_proven.is_not(True),
            and_(
                or_(RuntimeOwnership.watchdog_id.is_not(None), RuntimeOwnership.watchdog_pid.is_not(None)),
                or_(
                    RuntimeOwnership.watchdog_state.is_(None),
                    RuntimeOwnership.watchdog_state.not_in((WatchdogProcessState.STOPPED, WatchdogProcessState.CRASHED)),
                ),
            ),
        ),
    ).exists()
    safe_session = db.select(Session.id).where(
        Session.id == DeviceConfig.claimed_session_id,
        Session.command_in_flight.is_(False),
        Session.runtime_port.is_(None),
        Session.runtime_token.is_(None),
        or_(
            Session.status.in_((SessionStatus.COMPLETED, SessionStatus.CANCELLED)),
            and_(
                Session.status.in_((SessionStatus.PREPARING, SessionStatus.SCHEDULED)),
                Session.command_id.is_(None),
                Session.dataflow_id.is_(None),
                Session.watchdog_id.is_(None),
                Session.started_at.is_(None),
                ~db.select(RuntimeOwnership.id).where(
                    RuntimeOwnership.session_id == Session.id,
                ).exists(),
            ),
        ),
    ).exists()
    return and_(safe_session, ~unresolved_runtime)


def _claim_snapshot(row: DeviceConfig):
    """Fence mutations against the exact owner, state, and lease observed."""
    return and_(
        DeviceConfig.id == row.id,
        DeviceConfig.claimed_session_id == row.claimed_session_id,
        DeviceConfig.claim_state == row.claim_state,
        DeviceConfig.claim_expires_at == row.claim_expires_at,
    )


def _update_claim(row: DeviceConfig, *, values: dict, condition=None) -> DeviceConfig:
    config_id = row.id
    predicate = _claim_snapshot(row)
    if condition is not None:
        predicate = and_(predicate, condition)
    with transaction():
        result = db.session.execute(
            db.update(DeviceConfig).where(predicate).values(**values),
            execution_options={"synchronize_session": False},
        )
        if result.rowcount != 1:
            db.session.refresh(row)
            raise DeviceClaimConflict(config_id, claimed_session_id=row.claimed_session_id)
    db.session.refresh(row)
    return row


def claim(
    config_id: int,
    session_id: int,
    *,
    force: bool = False,
    starting: bool = False,
    lease_seconds: int = STARTING_CLAIM_LEASE_SECONDS,
) -> DeviceConfig:
    """Atomically acquire a claim; force cannot override unresolved ownership."""
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be greater than zero")
    row = _require(config_id)
    now = datetime.now(UTC)
    condition = None
    if row.claim_state is not DeviceClaimState.FREE:
        if row.claimed_session_id == session_id:
            # Even idempotent calls check the database rather than accepting a
            # stale identity-map observation as proof of current ownership.
            expiry = row.claim_expires_at
            if starting and row.claim_state is DeviceClaimState.STARTING:
                expiry = now + timedelta(seconds=lease_seconds)
            return _update_claim(row, values={"claim_expires_at": expiry})
        expiry = row.claim_expires_at
        if expiry is not None and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        expired = row.claim_state is DeviceClaimState.STARTING and expiry is not None and expiry <= now
        if not force and not expired:
            raise DeviceClaimConflict(config_id, claimed_session_id=row.claimed_session_id)
        condition = _release_is_safe()
    else:
        condition = DeviceConfig.claimed_session_id.is_(None)
    return _update_claim(row, condition=condition, values={
        "claim_state": DeviceClaimState.STARTING if starting else DeviceClaimState.CLAIMED,
        "claimed_session_id": session_id,
        "claim_expires_at": now + timedelta(seconds=lease_seconds) if starting else None,
    })


def activate(config_id: int, session_id: int) -> DeviceConfig:
    """Promote only the named owner's current startup claim."""
    row = _require(config_id)
    if row.claimed_session_id != session_id or row.claim_state not in (
        DeviceClaimState.STARTING, DeviceClaimState.CLAIMED,
    ):
        raise DeviceClaimConflict(config_id, claimed_session_id=row.claimed_session_id)
    return _update_claim(row, values={
        "claim_state": DeviceClaimState.CLAIMED, "claim_expires_at": None,
    })


def release_expired_starting_claims(*, now: datetime | None = None) -> int:
    """Release expired reservations only when their owner is provably safe."""
    if "claim_expires_at" not in {
        column["name"] for column in inspect(db.engine).get_columns("device_configs")
    }:
        # Migration bootstrap runs before the pending schema is applied.
        return 0
    cutoff = now or datetime.now(UTC)
    with transaction():
        result = db.session.execute(
            db.update(DeviceConfig).where(
                DeviceConfig.claim_state == DeviceClaimState.STARTING,
                DeviceConfig.claim_expires_at.is_not(None),
                DeviceConfig.claim_expires_at <= cutoff,
                _release_is_safe(),
            ).values(claim_state=DeviceClaimState.FREE, claimed_session_id=None, claim_expires_at=None),
            execution_options={"synchronize_session": False},
        )
    return result.rowcount


def release(config_id: int, *, expected_session_id: int | None = None) -> DeviceConfig:
    """Release a safe owner with an atomic snapshot fence.

    Teardown callers should name their session so a delayed call cannot release
    a successor's reservation. The legacy no-owner form still fences its read
    snapshot and refuses active or unresolved runtime ownership.
    """
    row = _require(config_id)
    if row.claim_state is DeviceClaimState.FREE:
        return row
    if expected_session_id is not None and row.claimed_session_id != expected_session_id:
        raise DeviceClaimConflict(config_id, claimed_session_id=row.claimed_session_id)
    return _update_claim(row, condition=_release_is_safe(), values={
        "claim_state": DeviceClaimState.FREE, "claimed_session_id": None, "claim_expires_at": None,
    })


__all__ = [
    "InvalidHardwareId",
    "activate",
    "claim",
    "create",
    "create_from_template",
    "delete",
    "edit",
    "find_by_hardware_id",
    "get_by_id",
    "list",
    "rename",
    "release",
    "release_expired_starting_claims",
]
