"""Incidents resource — operator-facing failure/recovery history."""

from flask_smorest import Blueprint, abort

import app.services.incidents as incident_service
from app.api.schemas import (
    AckIncidentSchema,
    IncidentListQuerySchema,
    IncidentPageSchema,
    IncidentSchema,
)

blp = Blueprint(
    "incidents",
    __name__,
    url_prefix="/api/v1/incidents",
    description="Inspect and acknowledge operator-facing incidents.",
)


@blp.route("", methods=["GET"])
@blp.arguments(IncidentListQuerySchema, location="query")
@blp.response(200, IncidentPageSchema)
def list_incidents(query):
    try:
        return incident_service.list_page(
            session_id=query.get("session"),
            status=query.get("status"),
            page_size=query["page_size"],
            cursor=query.get("cursor"),
        )
    except ValueError as exc:
        abort(400, message=str(exc), code="invalid_cursor")


@blp.route("/<string:incident_id>", methods=["GET"])
@blp.response(200, IncidentSchema)
def get_incident(incident_id):
    return incident_service.get(incident_id)


@blp.route("/<string:incident_id>/ack", methods=["POST"])
@blp.arguments(AckIncidentSchema)
@blp.response(200, IncidentSchema)
def acknowledge_incident(payload, incident_id):
    return incident_service.acknowledge(
        incident_id,
        acknowledged_by=payload.get("acknowledged_by"),
        note=payload.get("note"),
    )
