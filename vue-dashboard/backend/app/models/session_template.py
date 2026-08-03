from datetime import UTC, datetime

from app.database import db


class SessionTemplate(db.Model):
    """Sourcing template from the physical folder and handle all the hash computation for identity and metadata reconcilation."""

    __tablename__ = "session_templates"

    template_id = db.Column(db.String(64), primary_key=True)
    relative_path = db.Column(db.String(1024), nullable=False, unique=True, index=True)
    registered_hash = db.Column(db.String(64), nullable=False, index=True)
    observed_hash = db.Column(db.String(64), nullable=True, index=True)
    filesystem_identity = db.Column(db.String(255), nullable=True)
    state = db.Column(db.String(32), nullable=False, default="registered", index=True)
    lineage_parent_id = db.Column(
        db.String(64),
        db.ForeignKey("session_templates.template_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    duplicate_of_template_id = db.Column(
        db.String(64),
        db.ForeignKey("session_templates.template_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    dependencies = db.relationship(
        "SessionTemplateDependency",
        back_populates="template",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class SessionTemplateDependency(db.Model):
    """Resolved dependency fingerprint metadata for a registered template."""

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
