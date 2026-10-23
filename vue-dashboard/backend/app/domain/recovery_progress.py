"""Bound recovery observations before they enter reports and API responses."""

import math
from collections.abc import Mapping


def _timestamp(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return value if math.isfinite(value) and value >= 0 else None
    except OverflowError:
        return None


def normalize_recovery_progress(value):
    """Keep observed stages and verification evidence in a bounded recovery history."""
    if not isinstance(value, Mapping) or not isinstance(value.get("stage"), str):
        return None
    stage = value["stage"].strip()[:80]
    if not stage:
        return None
    history = value.get("history")
    entries = []
    for item in history[-16:] if isinstance(history, list) else []:
        if not isinstance(item, Mapping) or not isinstance(item.get("stage"), str):
            continue
        at = _timestamp(item.get("at"))
        if at is None or not item["stage"].strip():
            continue
        attempt = item.get("attempt")
        entries.append({
            "stage": item["stage"].strip()[:80],
            "at": at,
            "attempt": attempt if isinstance(attempt, int) and not isinstance(attempt, bool)
            and attempt >= 0 else None,
        })
    error = value.get("last_error")
    return {
        "stage": stage,
        "started_at": _timestamp(value.get("started_at")),
        "ping_status": value.get("ping_status")
        if value.get("ping_status") in ("pending", "passed", "failed") else None,
        "verification": value.get("verification")
        if value.get("verification") in ("ping", "data") else None,
        "last_error": error[:500] if isinstance(error, str) else None,
        "history": entries,
    }
