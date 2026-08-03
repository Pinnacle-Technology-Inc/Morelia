"""Repository helpers for the metadata-only template registry."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.database import db
from app.models.session_template import SessionTemplate, SessionTemplateDependency


class SessionTemplateRepository:
    """Database access for filesystem-owned template metadata."""

    def create(
        self,
        *,
        relative_path: str,
        registered_hash: str,
        template_id: str | None = None,
        observed_hash: str | None = None,
        filesystem_identity: str | None = None,
        state: str = "registered",
        lineage_parent_id: str | None = None,
        duplicate_of_template_id: str | None = None,
    ) -> SessionTemplate:
        row = SessionTemplate(
            template_id=template_id or uuid4().hex,
            relative_path=relative_path,
            registered_hash=registered_hash,
            observed_hash=observed_hash,
            filesystem_identity=filesystem_identity,
            state=state,
            lineage_parent_id=lineage_parent_id,
            duplicate_of_template_id=duplicate_of_template_id,
        )
        db.session.add(row)
        db.session.flush()
        return row

    def get_by_id(self, template_id: str) -> SessionTemplate | None:
        return db.session.get(SessionTemplate, template_id)

    def get_by_path(self, relative_path: str) -> SessionTemplate | None:
        return db.session.scalars(
            db.select(SessionTemplate).where(SessionTemplate.relative_path == relative_path)
        ).first()

    def list(self) -> list[SessionTemplate]:
        return db.session.scalars(
            db.select(SessionTemplate).order_by(SessionTemplate.relative_path)
        ).all()

    def update_state(self, template_id: str, state: str) -> SessionTemplate:
        row = self._require(template_id)
        row.state = state
        row.updated_at = datetime.now(UTC)
        db.session.flush()
        return row

    def record_observation(
        self,
        template_id: str,
        *,
        observed_hash: str,
        filesystem_identity: str | None = None,
        state: str | None = None,
    ) -> SessionTemplate:
        row = self._require(template_id)
        row.observed_hash = observed_hash
        row.filesystem_identity = filesystem_identity
        if state is not None:
            row.state = state
        row.updated_at = datetime.now(UTC)
        db.session.flush()
        return row

    def set_lineage(
        self,
        template_id: str,
        *,
        lineage_parent_id: str | None = None,
        duplicate_of_template_id: str | None = None,
    ) -> SessionTemplate:
        row = self._require(template_id)
        row.lineage_parent_id = lineage_parent_id
        row.duplicate_of_template_id = duplicate_of_template_id
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

    @staticmethod
    def _require(template_id: str) -> SessionTemplate:
        row = db.session.get(SessionTemplate, template_id)
        if row is None:
            raise LookupError(f"template not found: {template_id}")
        return row
