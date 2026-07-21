from app.database import db


class RuntimeManifest(db.Model):
    """Persisted snapshot of a resolved runtime manifest.

    Stores the canonical content JSON and its SHA-256 hash so the supervisor
    can match a re-attaching runtime host without re-resolving the manifest.
    ``Manifest.from_dict(row.content).hash == row.hash`` is always true.
    """

    __tablename__ = "runtime_manifests"

    id = db.Column(db.Integer, primary_key=True)
    hash = db.Column(db.String(64), nullable=False, unique=True)
    schema_version = db.Column(db.String(8), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=False)
    content = db.Column(db.JSON, nullable=False)
