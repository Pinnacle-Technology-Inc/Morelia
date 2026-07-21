"""In-memory representation of a device-template file.

Device templates are deliberately not SQLAlchemy models.  Their authoritative
state is the TOML file under ``instance/device-templates``; this object is only
the validated result returned by the service and API layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class DeviceTemplate:
    name: str
    file_path: str
    type: str
    content: dict[str, Any]
    content_hash: str
    created_at: datetime | None = None
