"""Recovery-gaps resource — output-continuity gaps left by recoveries."""

from flask_smorest import Blueprint

import app.services.gaps as gap_service
from app.api.schemas import GapListQuerySchema, RecoveryGapSchema

blp = Blueprint(
    "gaps",
    __name__,
    url_prefix="/api/v1/gaps",
    description="Inspect recovery output-continuity gaps.",
)


@blp.route("", methods=["GET"])
@blp.arguments(GapListQuerySchema, location="query")
@blp.response(200, RecoveryGapSchema(many=True))
def list_gaps(query):
    return gap_service.list_for_session(query["session"])
