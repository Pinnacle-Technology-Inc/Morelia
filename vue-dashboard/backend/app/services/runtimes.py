"""Runtime ownership read services."""

from app.database import db
from app.models.runtime_ownership import RuntimeOwnership
from app.repositories.runtime_ownership import ACTIVE_RUNTIME_STATES


def list_runtimes() -> list[RuntimeOwnership]:
    """Return active runtime ownership rows, newest first."""
    return db.session.scalars(
        db.select(RuntimeOwnership)
        .where(RuntimeOwnership.state.in_(ACTIVE_RUNTIME_STATES))
        .order_by(RuntimeOwnership.started_at.desc(), RuntimeOwnership.id.desc())
    ).all()
