"""Incidents resource — operator-facing failure/recovery history."""

from flask_smorest import Blueprint

import app.services.incidents as incident_service
from app.api.schemas import (
    AckIncidentSchema,
    IncidentListQuerySchema,
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
@blp.response(200, IncidentSchema(many=True))
def list_incidents(query):
    return incident_service.list_for_session(query["session"], status=query.get("status"))


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
