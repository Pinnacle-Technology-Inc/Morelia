"""Non-mutating, deterministic assignment planning for session templates."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from flask import current_app

from app.services import device_templates
from app.services.device_list import build_pool_rows
from app.services import session_templates


def _device_type_for_flow(flow: Mapping) -> str | None:
    """Resolve a flow's device type from path or portable name form.

    Stored templates use ``device_template_path``; local library drafts may also
    carry the CLI-portable ``device_template`` name. Either is enough to pick a
    compatible pool type for planning.
    """
    path = flow.get("device_template_path")
    if isinstance(path, str) and path.strip():
        template = device_templates.get_by_path(path)
        if template is not None:
            return template.type
        template = device_templates.get_by_name(Path(path).stem)
        if template is not None:
            return template.type
    name = flow.get("device_template")
    if isinstance(name, str) and name.strip():
        template = device_templates.get_by_name(name)
        if template is not None:
            return template.type
    return None


def plan(reference: str) -> dict[str, object]:
    template = session_templates.resolve_for_plan(reference)
    scan = current_app.extensions["device_discovery_service"].scan()
    pool = build_pool_rows(scan.devices)
    available = sorted(
        (
            row for row in pool
            if row.get("status") == "free"
            and row.get("availability") == "available"
            and isinstance(row.get("id"), int)
        ),
        key=lambda row: (str(row.get("type", "")), str(row.get("hardware_id", "")), str(row.get("port", "")), int(row["id"])),
    )
    remaining = list(available)
    assignments: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    unresolved: list[dict[str, object]] = []
    flows = (template.content or {}).get("device_flows", [])
    for index, flow in enumerate(flows):
        flow = flow if isinstance(flow, Mapping) else {}
        device_type = _device_type_for_flow(flow)
        requested = flow.get("hardware_id")
        candidates = [row for row in remaining if row.get("type") == device_type]
        exact = [row for row in candidates if requested and row.get("hardware_id") == requested]
        chosen = exact[0] if exact else (candidates[0] if not requested and candidates else None)
        if chosen is not None:
            assignments.append({
                "flow_index": index,
                "device_config_id": chosen["id"],
                "device_type": chosen["type"],
                "hardware_id": chosen["hardware_id"],
                "port": chosen["port"],
                "match": "exact" if requested else "generic",
            })
            remaining.remove(chosen)
            continue
        alternatives = [
            {"device_config_id": row["id"], "device_type": row["type"], "hardware_id": row["hardware_id"], "port": row["port"]}
            for row in candidates
        ]
        if requested:
            warnings.append({
                "flow_index": index, "code": "identity_unavailable",
                "message": f"Requested hardware identity {requested!r} is not free and available.",
                "requested_hardware_id": requested, "alternatives": alternatives,
            })
            unresolved.append({
                "flow_index": index, "code": "identity_unavailable",
                "message": f"Requested hardware identity {requested!r} is unavailable.",
                "device_type": device_type, "requested_hardware_id": requested,
            })
        else:
            unresolved.append({
                "flow_index": index, "code": "no_compatible_device",
                "message": f"No free and available {device_type or 'compatible'} device exists.",
                "device_type": device_type, "requested_hardware_id": None,
            })
    return {
        "template_name": template.name,
        "scan_id": scan.scan_id,
        "scanned_at": scan.scanned_at,
        "assignments": assignments,
        "warnings": warnings,
        "unresolved_requirements": unresolved,
        "complete": len(assignments) == len(flows),
    }
