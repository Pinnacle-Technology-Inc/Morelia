"""Repository helpers for the named session-template library."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.database import db
from app.models.session_template import SessionTemplate


class SessionTemplateRepository:
    """Database access for reusable session templates."""

    def create(
        self,
        *,
        name: str,
        content: Mapping[str, Any],
        content_hash: str,
    ) -> SessionTemplate:
        row = SessionTemplate(name=name, content=dict(content), content_hash=content_hash)
        db.session.add(row)
        db.session.flush()
        return row

    def get_by_id(self, template_id: int) -> SessionTemplate | None:
        return db.session.get(SessionTemplate, template_id)

    def get_by_name(self, name: str) -> SessionTemplate | None:
        return db.session.scalars(
            db.select(SessionTemplate).where(SessionTemplate.name == name)
        ).first()

    def list(self) -> list[SessionTemplate]:
        return db.session.scalars(
            db.select(SessionTemplate).order_by(SessionTemplate.name)
        ).all()

    def delete(self, row: SessionTemplate) -> None:
        db.session.delete(row)
