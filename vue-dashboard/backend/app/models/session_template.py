"""Metadata-only registry for file-authoritative session templates."""

from datetime import UTC, datetime

from sqlalchemy import text

from app.database import db


class SessionTemplate(db.Model):
    """Durable identity and observations; never stores runnable template content."""

    __tablename__ = "session_templates"

    template_id = db.Column(db.String(64), primary_key=True)
    relative_path = db.Column(db.String(1024), nullable=False, index=True)
    registered_hash = db.Column(db.String(64), nullable=False, index=True)
    observed_hash = db.Column(db.String(64), nullable=True, index=True)
    filesystem_identity = db.Column(db.String(255), nullable=True)
    lifecycle_state = db.Column(db.String(32), nullable=False, default="PENDING", index=True)
    integrity_state = db.Column(db.String(32), nullable=False, default="UNKNOWN", index=True)
    lineage_parent_id = db.Column(
        db.String(64),
        db.ForeignKey("session_templates.template_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        db.CheckConstraint(
            "lifecycle_state IN ('PENDING', 'ACTIVE', 'ARCHIVED', 'REPLACED')",
            name="ck_session_templates_lifecycle_state",
        ),
        db.CheckConstraint(
            "integrity_state IN ('UNKNOWN', 'MATCHED', 'CHANGED', 'MISSING', 'INVALID')",
            name="ck_session_templates_integrity_state",
        ),
        db.Index(
            "uq_session_templates_current_path",
            "relative_path",
            unique=True,
            sqlite_where=text("lifecycle_state != 'REPLACED'"),
        ),
        db.Index(
            "uq_session_templates_current_hash",
            "registered_hash",
            unique=True,
            sqlite_where=text("lifecycle_state != 'REPLACED'"),
        ),
    )

    dependencies = db.relationship(
        "SessionTemplateDependency",
        back_populates="template",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def state(self) -> str:
        """Derive the API display state from durable lifecycle and integrity axes."""

        if self.lifecycle_state != "ACTIVE":
            return self.lifecycle_state
        return "ACTIVE" if self.integrity_state == "MATCHED" else self.integrity_state


class SessionTemplateDependency(db.Model):
    """Resolved dependency fingerprints for one registry identity."""

    __tablename__ = "session_template_dependencies"

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(
        db.String(64),
        db.ForeignKey("session_templates.template_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relative_path = db.Column(db.String(1024), nullable=False)
    resolved_hash = db.Column(db.String(64), nullable=False)
    fingerprint = db.Column(db.String(64), nullable=False, index=True)
    resolved_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    template = db.relationship("SessionTemplate", back_populates="dependencies")
