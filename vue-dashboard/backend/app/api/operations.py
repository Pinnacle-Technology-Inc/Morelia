"""Operations resource for durable command reconciliation and resolution."""

from flask_smorest import Blueprint

import app.services.operations as operation_service
from app.api.schemas import (
    OperationListQuerySchema,
    OperationSchema,
    ResolveOperationSchema,
)

blp = Blueprint(
    "operations",
    __name__,
    url_prefix="/api/v1/operations",
    description="Inspect and resolve durable runtime operations.",
)


@blp.route("/", methods=["GET"])
@blp.arguments(OperationListQuerySchema, location="query")
@blp.response(200, OperationSchema(many=True))
def list_operations(query):
    return operation_service.list_operations(
        state=query.get("state"),
        session_id=query.get("session_id"),
        dataflow_id=query.get("dataflow_id"),
    )


@blp.route("/<string:operation_id>", methods=["GET"])
@blp.response(200, OperationSchema)
def get_operation(operation_id):
    return operation_service.get_operation(operation_id)


@blp.route("/<string:operation_id>/resolve", methods=["POST"])
@blp.arguments(ResolveOperationSchema)
@blp.response(200, OperationSchema)
def resolve_operation(payload, operation_id):
    return operation_service.resolve_uncertain_operation(
        operation_id,
        outcome=payload["outcome"],
        resolved_by=payload["resolved_by"],
        resolution_note=payload["resolution_note"],
    )
