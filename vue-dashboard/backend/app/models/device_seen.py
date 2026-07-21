from datetime import UTC, datetime

from app.database import db


class DeviceSeen(db.Model):
    """One row per discovered device per scan — discovery evidence, not ownership.

    ``physical_device_id`` is a derived string (``"{device_type}:{hardware_id}"``,
    degrading to ``"unknown:<serial-or-empty>"``), not a foreign key: it is
    populated even for devices with no persisted ``device_config`` row, and
    equals a config's identity when one exists.
    """

    __tablename__ = "device_seen"

    id = db.Column(db.Integer, primary_key=True)
    physical_device_id = db.Column(db.String(255), nullable=False, index=True)
    scan_id = db.Column(db.String(64), nullable=False, index=True)
    seen_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    port = db.Column(db.String(255), nullable=False)
    availability = db.Column(db.String(16), nullable=False)
    display_label = db.Column(db.String(255), nullable=True)
    warnings_json = db.Column(db.JSON, nullable=True)
    raw_json = db.Column(db.JSON, nullable=True)
