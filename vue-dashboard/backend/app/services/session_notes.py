from app.domain.errors import SessionNoteNotFound, SessionNotFound
from app.models.session_note import SessionNote
from app.repositories.session_notes import SessionNoteRepository
from app.repositories.sessions import SessionRepository

MAX_NOTE_BODY_LENGTH = 4_000

_notes = SessionNoteRepository()
_sessions = SessionRepository()


def _require_session(session_id: int) -> None:
    if _sessions.get(session_id) is None:
        raise SessionNotFound(session_id)


def _clean_body(body: str) -> str:
    clean = body.strip()
    if not clean:
        raise ValueError("Note body must not be blank.")
    if len(clean) > MAX_NOTE_BODY_LENGTH:
        raise ValueError(f"Note body must be at most {MAX_NOTE_BODY_LENGTH} characters.")
    return clean


def list_page(
    session_id: int,
    *,
    limit: int,
    before_id: int | None = None,
) -> dict[str, object]:
    _require_session(session_id)
    items, has_more = _notes.list_page(session_id, limit=limit, before_id=before_id)
    return {
        "items": items,
        "has_more": has_more,
        "next_before_id": items[-1].id if has_more and items else None,
    }


def create(session_id: int, *, body: str, show_timestamp: bool = False) -> SessionNote:
    _require_session(session_id)
    return _notes.create(
        session_id,
        body=_clean_body(body),
        show_timestamp=bool(show_timestamp),
    )


def update(
    session_id: int,
    note_id: int,
    *,
    body: str | None = None,
    show_timestamp: bool | None = None,
) -> SessionNote:
    _require_session(session_id)
    note = _notes.get(note_id)
    if note is None or note.session_id != session_id:
        raise SessionNoteNotFound(session_id, note_id)
    updated = _notes.update(
        note_id,
        body=_clean_body(body) if body is not None else None,
        show_timestamp=show_timestamp,
    )
    if updated is None:
        raise SessionNoteNotFound(session_id, note_id)
    return updated

