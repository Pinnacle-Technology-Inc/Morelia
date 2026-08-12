from datetime import UTC, datetime
from uuid import uuid4

from app.database import db


class Experiment(db.Model):
    """Organizational grouping for sessions; never a runtime owner."""

    __tablename__ = "experiments"

    id = db.Column(db.String(64), primary_key=True, default=lambda: uuid4().hex)
    name = db.Column(
        db.String(255, collation="NOCASE"),
        nullable=False,
        unique=True,
        index=True,
    )
    description = db.Column(db.Text, nullable=True)
    archived_at = db.Column(db.DateTime(timezone=True), nullable=True)
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
