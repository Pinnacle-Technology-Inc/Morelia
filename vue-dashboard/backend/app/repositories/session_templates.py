"""Repository helpers for metadata-only file-template registry rows."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.database import db
from app.models.session_template import SessionTemplate, SessionTemplateDependency

LIFECYCLE_STATES = frozenset({"PENDING", "ACTIVE", "ARCHIVED", "REPLACED"})
INTEGRITY_STATES = frozenset({"UNKNOWN", "MATCHED", "CHANGED", "MISSING", "INVALID"})


class SessionTemplateRepository:
    """Flush-only persistence primitives for registry identity and observations."""

    def create(
        self,
        *,
        relative_path: str,
        registered_hash: str,
        template_id: str | None = None,
        observed_hash: str | None = None,
        filesystem_identity: str | None = None,
        lifecycle_state: str = "PENDING",
        integrity_state: str = "UNKNOWN",
        lineage_parent_id: str | None = None,
    ) -> SessionTemplate:
        self._validate_states(lifecycle_state, integrity_state)
        row = SessionTemplate(
            template_id=template_id or uuid4().hex,
            relative_path=relative_path,
            registered_hash=registered_hash,
            observed_hash=observed_hash,
            filesystem_identity=filesystem_identity,
            lifecycle_state=lifecycle_state,
            integrity_state=integrity_state,
            lineage_parent_id=lineage_parent_id,
        )
        db.session.add(row)
        db.session.flush()
        return row

    def get_by_id(self, template_id: str) -> SessionTemplate | None:
        return db.session.get(SessionTemplate, template_id)

    def list(self) -> list[SessionTemplate]:
        return db.session.scalars(
            db.select(SessionTemplate).order_by(SessionTemplate.relative_path)
        ).all()

    def transition(
        self,
        template_id: str,
        *,
        lifecycle_state: str,
        integrity_state: str,
    ) -> SessionTemplate:
        self._validate_states(lifecycle_state, integrity_state)
        row = self._require(template_id)
        row.lifecycle_state = lifecycle_state
        row.integrity_state = integrity_state
        row.updated_at = datetime.now(UTC)
        db.session.flush()
        return row

    def reconcile(
        self,
        template_id: str,
        *,
        relative_path: str,
        registered_hash: str,
        observed_hash: str | None,
        filesystem_identity: str | None,
        lifecycle_state: str,
        integrity_state: str,
        lineage_parent_id: str | None = None,
    ) -> SessionTemplate:
        self._validate_states(lifecycle_state, integrity_state)
        row = self._require(template_id)
        desired = (
            relative_path,
            registered_hash,
            observed_hash,
            filesystem_identity,
            lifecycle_state,
            integrity_state,
            lineage_parent_id,
        )
        current = (
            row.relative_path,
            row.registered_hash,
            row.observed_hash,
            row.filesystem_identity,
            row.lifecycle_state,
            row.integrity_state,
            row.lineage_parent_id,
        )
        if current != desired:
            row.relative_path = relative_path
            row.registered_hash = registered_hash
            row.observed_hash = observed_hash
            row.filesystem_identity = filesystem_identity
            row.lifecycle_state = lifecycle_state
            row.integrity_state = integrity_state
            row.lineage_parent_id = lineage_parent_id
            row.updated_at = datetime.now(UTC)
            db.session.flush()
        return row

    def replace_dependencies(
        self,
        template_id: str,
        dependencies: Iterable[Mapping[str, Any]],
    ) -> list[SessionTemplateDependency]:
        row = self._require(template_id)
        row.dependencies.clear()
        for dependency in dependencies:
            row.dependencies.append(
                SessionTemplateDependency(
                    relative_path=dependency["relative_path"],
                    resolved_hash=dependency["resolved_hash"],
                    fingerprint=dependency["fingerprint"],
                    resolved_at=dependency.get("resolved_at", datetime.now(UTC)),
                )
            )
        row.updated_at = datetime.now(UTC)
        db.session.flush()
        return list(row.dependencies)

    def list_dependencies(self, template_id: str) -> list[SessionTemplateDependency]:
        self._require(template_id)
        return db.session.scalars(
            db.select(SessionTemplateDependency)
            .where(SessionTemplateDependency.template_id == template_id)
            .order_by(SessionTemplateDependency.relative_path)
        ).all()

    def delete(self, row: SessionTemplate) -> None:
        db.session.delete(row)
        db.session.flush()

    @staticmethod
    def _require(template_id: str) -> SessionTemplate:
        row = db.session.get(SessionTemplate, template_id)
        if row is None:
            raise LookupError(f"template registry row not found: {template_id}")
        return row

    @staticmethod
    def _validate_states(lifecycle_state: str, integrity_state: str) -> None:
        if lifecycle_state not in LIFECYCLE_STATES:
            raise ValueError(f"unknown template lifecycle state: {lifecycle_state!r}")
        if integrity_state not in INTEGRITY_STATES:
            raise ValueError(f"unknown template integrity state: {integrity_state!r}")
