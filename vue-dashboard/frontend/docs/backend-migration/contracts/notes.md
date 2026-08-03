# v1 Session and history notes contract

Status: accepted 2026-07-22; implementation intentionally deferred to a future packet.

## Targets and fields

A note targets exactly one session, experiment, or data gap. It contains `note_id`, target identity, `author_id`/display name, `created_at`, body, and correlation ids when the note was created from an incident, gap, operation, or event. Body is UTF-8 plain text, trimmed, with a 4,000-character maximum; empty bodies are invalid.

## Durability and audit

Notes are append-only. Editing creates a new immutable revision linked to the prior note; deletion is a tombstone retaining prior body, actor, time, reason, and correlation ids. Completed sessions and archived experiments may receive notes; this is the sole permitted post-archive metadata action. Notes never alter lifecycle, incident status, operation outcome, or scientific data. Every create/revise/delete requires a request key; same key and payload is idempotent, mismatched reuse returns `request_key_conflict`.

## API and UI

V1 has no authentication principal. Create accepts a trimmed operator-supplied author string (1–255 chars), stored verbatim and visibly labeled operator supplied. Body is trimmed UTF-8 plain text, 1–4000 chars. `GET /api/v1/<target>/<id>/notes` returns bounded newest-first note rows. `POST` accepts `{author, body, request_key, correlation}`. Revisions/deletes require actor string and reason. Correlation fields are optional typed `incident_id`, `gap_id`, `operation_id`, `recovery_id`, and `event_id`; they never change target identity.

Session Detail and the Incidents & Gaps page will render the same durable note identity in Activity/Notes.
