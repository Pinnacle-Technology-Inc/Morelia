from datetime import UTC, datetime

from app.database import db, transaction
from app.models.session_note import SessionNote


class SessionNoteRepository:
    def list_page(
        self,
        session_id: int,
        *,
        limit: int,
        before_id: int | None = None,
    ) -> tuple[list[SessionNote], bool]:
        query = db.select(SessionNote).where(SessionNote.session_id == session_id)
        if before_id is not None:
            query = query.where(SessionNote.id < before_id)
        rows = db.session.scalars(
            query.order_by(SessionNote.created_at.desc(), SessionNote.id.desc()).limit(limit + 1)
        ).all()
        return rows[:limit], len(rows) > limit

    def get(self, note_id: int) -> SessionNote | None:
        return db.session.get(SessionNote, note_id)

    def create(self, session_id: int, *, body: str, show_timestamp: bool) -> SessionNote:
        with transaction():
            note = SessionNote(
                session_id=session_id,
                body=body,
                show_timestamp=show_timestamp,
            )
            db.session.add(note)
            db.session.flush()
        return note

    def update(
        self,
        note_id: int,
        *,
        body: str | None = None,
        show_timestamp: bool | None = None,
    ) -> SessionNote | None:
        with transaction():
            note = self.get(note_id)
            if note is None:
                return None
            if body is not None:
                note.body = body
            if show_timestamp is not None:
                note.show_timestamp = show_timestamp
            note.updated_at = datetime.now(UTC)
            db.session.flush()
        return note

