from datetime import UTC, datetime

from app.database import db


class SessionTemplate(db.Model):
    """A reusable session composition referencing device-template files."""

    __tablename__ = "session_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True, index=True)
    content = db.Column(db.JSON, nullable=False)
    content_hash = db.Column(db.String(64), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(UTC))
