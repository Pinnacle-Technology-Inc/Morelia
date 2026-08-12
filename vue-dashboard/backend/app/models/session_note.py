from datetime import UTC, datetime

from app.database import db


class SessionNote(db.Model):
    """Operator annotation owned by one session."""

    __tablename__ = "session_notes"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer,
        db.ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    body = db.Column(db.Text, nullable=False)
    show_timestamp = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        db.Index(
            "ix_session_notes_session_created",
            "session_id",
            "created_at",
            "id",
        ),
    )

