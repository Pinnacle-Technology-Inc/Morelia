"""Recovery-gaps resource — output-continuity gaps left by recoveries."""

from flask_smorest import Blueprint, abort

import app.services.gaps as gap_service
from app.api.schemas import GapListQuerySchema, GapPageSchema, RecoveryGapSchema

blp = Blueprint(
    "gaps",
    __name__,
    url_prefix="/api/v1/gaps",
    description="Inspect recovery output-continuity gaps.",
)


@blp.route("", methods=["GET"])
@blp.arguments(GapListQuerySchema, location="query")
@blp.response(200, GapPageSchema)
def list_gaps(query):
    try:
        return gap_service.list_page(
            session_id=query.get("session"),
            confidence=query.get("confidence"),
            page_size=query["page_size"],
            cursor=query.get("cursor"),
        )
    except ValueError as exc:
        abort(400, message=str(exc), code="invalid_cursor")
