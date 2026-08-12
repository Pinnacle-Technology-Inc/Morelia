from flask import request
from flask_smorest import Blueprint, abort

import app.services.experiments as service
from app.api.schemas import ExperimentCreateSchema, ExperimentSchema, ExperimentUpdateSchema

blp = Blueprint("experiments", __name__, url_prefix="/api/v1/experiments")


def _handle(exc):
    abort(409 if exc.code != "experiment_not_found" else 404, message=str(exc), code=exc.code)


@blp.route("", methods=["GET"])
@blp.response(200, ExperimentSchema(many=True))
def list_experiments():
    include_archived = (
        str(request.args.get("include_archived", "false")).lower() == "true"
    )
    return service.list_all(include_archived=include_archived)


@blp.route("", methods=["POST"])
@blp.arguments(ExperimentCreateSchema)
@blp.response(201, ExperimentSchema)
def create_experiment(payload):
    try:
        return service.create(**payload)
    except (service.ExperimentError, ValueError) as exc:
        _handle(exc)


@blp.route("/<string:experiment_id>", methods=["GET"])
@blp.response(200, ExperimentSchema)
def get_experiment(experiment_id):
    return service.get(experiment_id)


@blp.route("/<string:experiment_id>", methods=["PUT", "PATCH"])
@blp.arguments(ExperimentUpdateSchema)
@blp.response(200, ExperimentSchema)
def update_experiment(payload, experiment_id):
    try:
        return service.update(experiment_id, **payload)
    except (service.ExperimentError, ValueError) as exc:
        _handle(exc)


@blp.route("/<string:experiment_id>/archive", methods=["POST"])
@blp.response(200, ExperimentSchema)
def archive_experiment(experiment_id):
    try:
        return service.archive(experiment_id)
    except service.ExperimentError as exc:
        _handle(exc)


@blp.route("/<string:experiment_id>", methods=["DELETE"])
@blp.response(204)
def delete_experiment(experiment_id):
    try:
        service.delete(experiment_id)
    except service.ExperimentError as exc:
        _handle(exc)
    return ""
