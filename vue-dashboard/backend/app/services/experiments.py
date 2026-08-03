from __future__ import annotations

from datetime import UTC, datetime

from app.models.experiment import Experiment
from app.repositories.experiments import ExperimentRepository

_repo = ExperimentRepository()


class ExperimentError(Exception):
    code = "experiment_error"


class ExperimentNotFound(ExperimentError):
    code = "experiment_not_found"


class ExperimentNameConflict(ExperimentError):
    code = "experiment_name_conflict"


class ExperimentArchived(ExperimentError):
    code = "experiment_archived"


class ExperimentHasSessions(ExperimentError):
    code = "experiment_has_sessions"


def _normalize_name(name: str) -> str:
    normalized = str(name or "").strip()
    if not normalized:
        raise ValueError("experiment name is required")
    return normalized


def _get(experiment_id: str) -> Experiment:
    row = _repo.get(experiment_id)
    if row is None:
        raise ExperimentNotFound(experiment_id)
    return row


def list_all(*, include_archived: bool = False) -> list[Experiment]:
    return _repo.list(include_archived=include_archived)


def get(experiment_id: str) -> Experiment:
    return _get(experiment_id)


def create(*, name: str, description: str | None) -> Experiment:
    normalized = _normalize_name(name)
    if _repo.get_by_name(normalized) is not None:
        raise ExperimentNameConflict(normalized)
    return _repo.create(name=normalized, description=description)


def update(experiment_id: str, *, name: str, description: str | None) -> Experiment:
    row = _get(experiment_id)
    if row.archived_at is not None:
        raise ExperimentArchived(experiment_id)
    normalized = _normalize_name(name)
    other = _repo.get_by_name(normalized)
    if other is not None and other.id != row.id:
        raise ExperimentNameConflict(normalized)
    return _repo.update(row, name=normalized, description=description)


def archive(experiment_id: str) -> Experiment:
    row = _get(experiment_id)
    if row.archived_at is None:
        return _repo.archive(row)
    return row


def delete(experiment_id: str) -> None:
    row = _get(experiment_id)
    if _repo.references(experiment_id):
        raise ExperimentHasSessions(experiment_id)
    _repo.delete(row)


def ensure_assignable(experiment_id: str | None) -> None:
    if experiment_id is None:
        return
    row = _get(experiment_id)
    if row.archived_at is not None:
        raise ExperimentArchived(experiment_id)
