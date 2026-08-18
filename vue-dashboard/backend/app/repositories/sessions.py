from dataclasses import dataclass
from datetime import datetime

from app.database import db, transaction
from app.domain.enums import PolicyMode, SessionStatus
from app.models.session import Session


def default_session_name(session_id: int) -> str:
    """Legacy fallback for sessions that have no template provenance."""
    return f"Run {session_id}"


def template_session_name(template_name: str, requested_name: str | None, run_number: int) -> str:
    """Compose the operator-facing name of one template run."""
    label = str(requested_name or "").strip() or "Run"
    return f"{template_name.strip()} • {label} {run_number}"


def published_session_clause():
    """SQL predicate for sessions that may appear on public read surfaces."""
    return db.or_(
        Session.creation_request_key.is_(None),
        Session.status != SessionStatus.PREPARING,
        Session.dataflow_id.isnot(None),
    )


@dataclass(frozen=True)
class SessionRunRef:
    """Enough of a session to name it, without loading the run itself."""

    id: int
    name: str
    status: SessionStatus
    created_at: datetime | None


@dataclass(frozen=True)
class TemplateRunHistory:
    """What one template revision has produced so far.

    ``latest`` is None only when ``run_count`` is 0 — a template that exists but
    has never been started.
    """

    run_count: int = 0
    latest: SessionRunRef | None = None


NO_RUNS = TemplateRunHistory()


class SessionRepository:

    def create(self, data: dict) -> Session:
        with transaction():
            requested_name = str(data.get("name") or "").strip()
            source_template_id = data.get("source_template_id")
            source_template_name = str(data.get("source_template_name") or "").strip()
            if source_template_id and source_template_name:
                session_name = self.next_template_session_name(
                    source_template_id,
                    source_template_name,
                    requested_name,
                )
            else:
                session_name = requested_name
            if session_name and not (source_template_id and source_template_name):
                suffix = 1
                while self.get_by_name(session_name) is not None:
                    session_name = f"{requested_name}-{suffix}"
                    suffix += 1
            row = Session(
                name=session_name,
                status=data.get("status", SessionStatus.PREPARING),
                policy=data.get("policy", PolicyMode.RECOMMEND),
                experiment_id=data.get("experiment_id"),
                notes=(str(data.get("notes")).strip() or None) if data.get("notes") is not None else None,
                schedule=data.get("schedule"),
                scheduled_for=data.get("scheduled_for"),
                schedule_claim_token=data.get("schedule_claim_token"),
                schedule_claim_expires_at=data.get("schedule_claim_expires_at"),
                cancellation_details=data.get("cancellation_details"),
                cancelled_at=data.get("cancelled_at"),
                device_flows=data.get("device_flows") or [],
                source_template_id=source_template_id,
                source_template_name=source_template_name or None,
                source_template_ref=data.get("source_template_ref"),
                source_template_hash=data.get("source_template_hash"),
                source_template_snapshot=data.get("source_template_snapshot"),
                creation_request_key=data.get("creation_request_key"),
                creation_request_fingerprint=data.get("creation_request_fingerprint"),
            )
            db.session.add(row)
            db.session.flush()
            if not row.name:
                row.name = default_session_name(row.id)
        return row

    def get(self, session_id: int) -> Session | None:
        return db.session.get(Session, session_id)

    def get_by_name(self, name: str) -> Session | None:
        return db.session.scalars(
            db.select(Session).where(Session.name == name.strip())
        ).first()

    def get_by_creation_request_key(self, request_key: str) -> Session | None:
        return db.session.scalars(
            db.select(Session).where(Session.creation_request_key == request_key)
        ).first()

    def due_scheduled(self, now: datetime) -> list[Session]:
        """Scheduled rows whose due time arrived and whose lease is available."""
        return db.session.scalars(
            db.select(Session)
            .where(
                Session.status == SessionStatus.SCHEDULED,
                Session.scheduled_for.is_not(None),
                Session.scheduled_for <= now,
                db.or_(
                    Session.schedule_claim_token.is_(None),
                    Session.schedule_claim_expires_at <= now,
                ),
            )
            .order_by(Session.scheduled_for.asc(), Session.id.asc())
        ).all()

    def try_claim_schedule(
        self,
        session_id: int,
        *,
        token: str,
        now: datetime,
        expires_at: datetime,
    ) -> bool:
        with transaction():
            result = db.session.execute(
                db.update(Session)
                .where(
                    Session.id == session_id,
                    Session.status == SessionStatus.SCHEDULED,
                    db.or_(
                        Session.schedule_claim_token.is_(None),
                        Session.schedule_claim_expires_at <= now,
                    ),
                )
                .values(
                    schedule_claim_token=token,
                    schedule_claim_expires_at=expires_at,
                )
            )
        return result.rowcount == 1

    def release_schedule_claim(self, session_id: int, token: str) -> None:
        with transaction():
            db.session.execute(
                db.update(Session)
                .where(
                    Session.id == session_id,
                    Session.schedule_claim_token == token,
                )
                .values(
                    schedule_claim_token=None,
                    schedule_claim_expires_at=None,
                )
            )

    def peek_next_id(self) -> int:
        """Guess the next session id for UI placeholders only — not reserved, can be stale."""
        highest = db.session.scalar(db.select(db.func.max(Session.id)))
        return (highest or 0) + 1

    def count_by_source_template_id(self, template_id: str) -> int:
        return int(
            db.session.scalar(
                db.select(db.func.count())
                .select_from(Session)
                .where(Session.source_template_id == template_id)
            )
            or 0
        )

    def next_template_session_name(
        self,
        template_id: str,
        template_name: str,
        requested_name: str | None = None,
    ) -> str:
        """Preview the next template-scoped name without reserving it."""
        run_number = self.count_by_source_template_id(template_id) + 1
        candidate = template_session_name(template_name, requested_name, run_number)
        while self.get_by_name(candidate) is not None:
            run_number += 1
            candidate = template_session_name(template_name, requested_name, run_number)
        return candidate

    def all(self) -> list[Session]:
        return db.session.scalars(db.select(Session)).all()

    def public_all(self) -> list[Session]:
        """Sessions that have crossed their public lifecycle boundary."""
        return db.session.scalars(
            db.select(Session).where(published_session_clause())
        ).all()

    def list_by_source_template_id(self, template_id: str) -> list[Session]:
        return db.session.scalars(
            db.select(Session)
            .where(Session.source_template_id == template_id)
            .order_by(Session.created_at.desc(), Session.id.desc())
        ).all()

    def run_history_by_source_template(self) -> dict[str, TemplateRunHistory]:
        """Run count and newest run for every template that has produced one.

        One indexed pass over ``ix_sessions_source_template_history`` rather than
        a query per template, and only the columns a caller needs to *name* a run
        — a session's frozen template snapshot is large and nothing here reads it.

        Templates with no runs are simply absent; callers substitute ``NO_RUNS``.
        """
        rows = db.session.execute(
            db.select(
                Session.source_template_id,
                Session.id,
                Session.name,
                Session.status,
                Session.created_at,
            )
            .where(
                Session.source_template_id.isnot(None),
                published_session_clause(),
            )
            .order_by(Session.created_at.desc(), Session.id.desc())
        ).all()

        history: dict[str, TemplateRunHistory] = {}
        for template_id, session_id, name, status, created_at in rows:
            previous = history.get(template_id)
            if previous is None:
                # Rows arrive newest-first, so the first one seen is the latest.
                history[template_id] = TemplateRunHistory(
                    run_count=1,
                    latest=SessionRunRef(
                        id=session_id,
                        name=name,
                        status=status,
                        created_at=created_at,
                    ),
                )
            else:
                history[template_id] = TemplateRunHistory(
                    run_count=previous.run_count + 1,
                    latest=previous.latest,
                )
        return history

    def set_runtime_host_identity(
        self,
        session: Session,
        *,
        port: int,
        token: str | None,
    ) -> None:
        with transaction():
            session.runtime_port = port
            session.runtime_token = token

    def clear_runtime_host_identity(self, session: Session) -> None:
        with transaction():
            session.runtime_port = None
            session.runtime_token = None

    def try_acquire_in_flight_lock(self, session_id: int) -> bool:
        """Atomic CAS: set command_in_flight=True only where it is currently False.

        Returns True if this call acquired the lock (exactly one row updated).
        Returns False if the lock was already held by another command.

        Must be called inside an active transaction() block so the caller can
        rollback on failure and release the lock automatically.
        """
        result = db.session.execute(
            db.update(Session)
            .where(Session.id == session_id, Session.command_in_flight == False)  # noqa: E712
            .values(command_in_flight=True)
        )
        return result.rowcount == 1

    def get_by_dataflow_id(self, dataflow_id: str) -> Session | None:
        return db.session.scalars(
            db.select(Session).where(Session.dataflow_id == dataflow_id)
        ).first()

    def mark_active_if_starting(self, dataflow_id: str) -> bool:
        """Promote STARTING only; late reports must not revive terminalizing runs."""
        with transaction():
            result = db.session.execute(
                db.update(Session)
                .where(
                    Session.dataflow_id == dataflow_id,
                    Session.status == SessionStatus.STARTING,
                )
                .values(status=SessionStatus.ACTIVE)
            )
        return result.rowcount == 1

    def with_dataflow_id(self) -> list[Session]:
        """Sessions that believe they own a dataflow — candidates for reconcile()."""
        return db.session.scalars(
            db.select(Session).where(Session.dataflow_id.isnot(None))
        ).all()

    def with_runtime_host_identity(self) -> list[Session]:
        """Sessions whose persisted host identity can be rehydrated on startup."""
        return db.session.scalars(
            db.select(Session).where(
                Session.dataflow_id.isnot(None),
                Session.runtime_port.isnot(None),
                Session.status.in_(
                    (
                        SessionStatus.STARTING,
                        SessionStatus.ACTIVE,
                        SessionStatus.ENDING,
                    )
                ),
            )
        ).all()

    def delete(self, session_id: int) -> None:
        with transaction():
            row = self.get(session_id)
            if row:
                db.session.delete(row)
