from app.database import db, transaction
from app.domain.enums import PolicyMode, SessionStatus
from app.models.session import Session


def default_session_name(session_id: int) -> str:
    """The name an unnamed session gets. Depends on the id, so it can only be
    minted after the insert.
    """
    return f"Session {session_id}"


class SessionRepository:

    def create(self, data: dict) -> Session:
        with transaction():
            requested_name = str(data.get("name") or "").strip()
            session_name = requested_name
            if session_name:
                suffix = 1
                while self.get_by_name(session_name) is not None:
                    session_name = f"{requested_name}-{suffix}"
                    suffix += 1
            row = Session(
                name=session_name,
                status=SessionStatus.DRAFT,
                policy=data.get("policy", PolicyMode.RECOMMEND),
                experiment_id=data.get("experiment_id"),
                schedule=data.get("schedule"),
                device_flows=data.get("device_flows") or [],
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

    def peek_next_id(self) -> int:
        """Best-effort guess at the id the next created session will get.

        NOT authoritative and NOT reserved — the real id is only ever
        assigned atomically by SQLite's own auto-increment at insert time
        (create(), via db.session.flush()). This is a plain unlocked read, so
        a concurrent create — or this one aborting before it commits — can
        make the guess wrong.

        Safe to be wrong: both consumers are cosmetic — a sink_location
        suggestion string (session_config._resolve_sink) and the name the
        create-session form shows as a placeholder (sessions.suggest_name).
        Neither decides a real row's identity. A stale guess just makes an odd
        filename or a placeholder that doesn't match the name create() ends up
        minting, never a duplicate row or a corrupted id sequence — unlike
        pre-computing MAX(id)+1 to use AS the actual id, which would be a
        real race.

        Note the placeholder consumer only stays safe as long as the form
        sends ``name: null`` when untouched. If it ever submitted the
        suggestion as an explicit name, a stale guess would collide and get a
        "-1" suffix from create()'s dedup loop.
        """
        highest = db.session.scalar(db.select(db.func.max(Session.id)))
        return (highest or 0) + 1

    def all(self) -> list[Session]:
        return db.session.scalars(db.select(Session)).all()

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
