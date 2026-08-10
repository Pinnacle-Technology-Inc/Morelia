"""Runtime ownership read services."""

from app.database import db
from app.models.runtime_ownership import RuntimeOwnership
from app.models.session import Session
from app.repositories.runtime_ownership import ACTIVE_RUNTIME_STATES
from app.repositories.sessions import published_session_clause


def list_runtimes() -> list[RuntimeOwnership]:
    """Return active runtime ownership rows, newest first."""
    return db.session.scalars(
        db.select(RuntimeOwnership)
        .join(Session, Session.id == RuntimeOwnership.session_id)
        .where(
            RuntimeOwnership.state.in_(ACTIVE_RUNTIME_STATES),
            published_session_clause(),
        )
        .order_by(RuntimeOwnership.started_at.desc(), RuntimeOwnership.id.desc())
    ).all()
