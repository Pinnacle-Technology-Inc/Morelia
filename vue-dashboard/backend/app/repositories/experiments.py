from datetime import UTC, datetime

from app.database import db, transaction
from app.models.experiment import Experiment
from app.models.session import Session


class ExperimentRepository:
    def get(self, experiment_id: str) -> Experiment | None:
        return db.session.get(Experiment, experiment_id)

    def get_by_name(self, name: str) -> Experiment | None:
        return db.session.scalars(db.select(Experiment).where(db.func.lower(Experiment.name) == name.lower())).first()

    def list(self, *, include_archived: bool = False) -> list[Experiment]:
        query = db.select(Experiment)
        if not include_archived:
            query = query.where(Experiment.archived_at.is_(None))
        return db.session.scalars(query.order_by(Experiment.updated_at.desc(), Experiment.id.desc())).all()

    def create(self, *, name: str, description: str | None) -> Experiment:
        with transaction():
            row = Experiment(name=name, description=description, created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
            db.session.add(row)
            db.session.flush()
        return row

    def references(self, experiment_id: str) -> int:
        return int(db.session.scalar(db.select(db.func.count()).select_from(Session).where(Session.experiment_id == experiment_id)) or 0)

    def update(self, row: Experiment, *, name: str, description: str | None) -> Experiment:
        with transaction():
            row.name = name
            row.description = description
            row.updated_at = datetime.now(UTC)
        return row

    def archive(self, row: Experiment) -> Experiment:
        with transaction():
            now = datetime.now(UTC)
            row.archived_at = now
            row.updated_at = now
        return row

    def delete(self, row: Experiment) -> None:
        with transaction():
            db.session.delete(row)
