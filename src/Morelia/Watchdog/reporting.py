"""Shape watchdog observations into stable, operator-facing reports.

Recovery code belongs in ``watchdog.py``.  This module owns presentation-only
choices: health summaries, compact wording, and the public recovery payload.
Keeping that boundary explicit prevents dashboard wording from obscuring the
hardware and heartbeat state machine.
"""

COMPACT_REASONS = {
    "worker_alive_heartbeat_fresh": "ok",
    "worker_not_alive": "worker not alive",
    "worker_alive_heartbeat_stale_below_threshold": "heartbeat stale, below threshold",
    "worker_alive_heartbeat_stale_threshold_reached": "heartbeat stale, threshold reached",
    "heartbeat_missing": "heartbeat missing",
    "no_data_below_threshold": "no data yet, below threshold",
    "no_data_threshold_reached": "no data, threshold reached",
    "first_packet_startup_grace": "waiting for first packet",
    "port_disconnect_heartbeat_window": "unplug detected",
    "connection_restored": "connection restored",
    "waiting_for_port": "port not connected",
    "stream_reconnecting": "reconnecting",
    "needs_action": "needs action",
    "manual_stop": "stopped by command",
}

HARDWARE_HEALTH = {
    "connected": "healthy",
    "reconnected": "healthy",
    "ping_failed": "suspect",
    "disconnected": "unhealthy",
}

_RECONNECT_FAILURE_REASONS = {
    "port_check_failed",
    "waiting_for_port",
    "waiting_for_port_release",
    "worker_cold_open_failed",
    "restart_failed",
    "restart_completed_worker_not_response",
    "waiting_for_heartbeat",
    "lifecycle_busy",
}


def summarize_watchdog_health(health_values):
    """Reduce item-level health values to one watchdog status."""
    if not health_values:
        return "unknown"
    if all(health == "healthy" for health in health_values):
        return "ok"
    if all(health == "unhealthy" for health in health_values):
        return "failed"
    return "degraded"


def build_compact_stream_report(verbose_stream):
    """Keep the fields needed by periodic summaries from one verbose report."""
    signals = verbose_stream["signals"]
    return {
        "stream_index": verbose_stream.get("stream_index"),
        "port": verbose_stream.get("port"),
        "port_owner": verbose_stream.get("port_owner"),
        "stream_health": verbose_stream.get("stream_health"),
        "worker_status": signals.get("worker", {}).get("status"),
        "heartbeat": signals.get("heartbeat", {}).get("status"),
        "failure_count": signals.get("failure", {}).get("count"),
        "action": verbose_stream.get("action", {}).get("taken"),
        "reason": COMPACT_REASONS.get(
            verbose_stream.get("rule"), verbose_stream.get("summary")
        ),
        "recovery_event": verbose_stream.get("recovery_event"),
    }


def assess_stream(
    *,
    worker,
    heartbeat,
    failure_reason,
    initiating_failure_reason,
    startup,
    count,
    threshold,
    max_heartbeat_age_sec,
):
    """Convert raw supervision signals into one health verdict and explanation."""
    worker_status = worker["status"]
    heartbeat_status = heartbeat.get("status")

    if failure_reason is None:
        return {
            "stream_health": "healthy",
            "rule": "worker_alive_heartbeat_fresh",
            "summary": "Worker is alive and heartbeat is fresh.",
        }

    if failure_reason == "port_absent_heartbeat_window":
        return {
            "stream_health": "suspect",
            "rule": "port_disconnect_heartbeat_window",
            "summary": (
                "Unplug detected; recording missing samples during the "
                f"{max_heartbeat_age_sec:g}-second heartbeat window."
            ),
        }

    if failure_reason == "waiting_for_port":
        return {
            "stream_health": "suspect",
            "rule": "waiting_for_port",
            "summary": (
                "Serial port is not connected; waiting for it to return. "
                f"Failure count is {count}/{threshold}."
            ),
        }

    if failure_reason in _RECONNECT_FAILURE_REASONS:
        return {
            "stream_health": "suspect",
            "rule": "stream_reconnecting",
            "summary": (
                f"Stream is recovering ({failure_reason}). "
                f"Failure count is {count}/{threshold}."
            ),
        }

    if failure_reason == "first_packet_pending":
        remaining = startup.get("remaining_sec") if isinstance(startup, dict) else None
        remaining_text = (
            f"{remaining:.1f}s" if isinstance(remaining, (int, float)) else "unknown"
        )
        return {
            "stream_health": "suspect",
            "rule": "first_packet_startup_grace",
            "summary": (
                "Waiting for the first data packet; startup grace has "
                f"{remaining_text} remaining."
            ),
        }

    if failure_reason == "needs_action":
        return {
            "stream_health": "unhealthy",
            "rule": "needs_action",
            "summary": (
                "Automatic recovery is paused"
                + (
                    f" after {initiating_failure_reason}"
                    if initiating_failure_reason
                    else ""
                )
                + "; stream is stopped and waiting for an explicit control-plane command."
            ),
        }

    if failure_reason == "manual_stop":
        return {
            "stream_health": "suspect",
            "rule": "manual_stop",
            "summary": "Stream is stopped by command.",
        }

    if worker_status != "alive":
        return {
            "stream_health": "unhealthy",
            "rule": "worker_not_alive",
            "summary": f"Worker is {worker_status}. Failure count is {count}/{threshold}.",
        }

    if heartbeat_status == "stale":
        age_sec = heartbeat.get("age_sec")
        age_text = f"{age_sec:.1f}s" if age_sec is not None else "unknown"
        if count < threshold:
            return {
                "stream_health": "suspect",
                "rule": "worker_alive_heartbeat_stale_below_threshold",
                "summary": (
                    f"Worker is alive, but heartbeat is stale for {age_text}. "
                    f"Failure count is {count}/{threshold}."
                ),
            }
        return {
            "stream_health": "unhealthy",
            "rule": "worker_alive_heartbeat_stale_threshold_reached",
            "summary": (
                f"Worker is alive, but heartbeat is stale for {age_text}. "
                f"Failure threshold reached at {count}/{threshold}."
            ),
        }

    if heartbeat_status == "missing":
        if failure_reason == "data_never_started":
            if count < threshold:
                return {
                    "stream_health": "suspect",
                    "rule": "no_data_below_threshold",
                    "summary": (
                        "HealthSink attached but no packet seen yet. "
                        f"Failure count is {count}/{threshold}."
                    ),
                }
            return {
                "stream_health": "unhealthy",
                "rule": "no_data_threshold_reached",
                "summary": (
                    "HealthSink attached but no packet ever arrived. "
                    f"Failure threshold reached at {count}/{threshold}."
                ),
            }
        return {
            "stream_health": "suspect",
            "rule": "heartbeat_missing",
            "summary": (
                f"Heartbeat is missing ({heartbeat.get('reason')}). "
                f"Failure count is {count}/{threshold}."
            ),
        }

    return {
        "stream_health": "suspect",
        "rule": "action_failure",
        "summary": f"{failure_reason}. Failure count is {count}/{threshold}.",
    }


def extract_action_error(action_result):
    """Return the most useful error raised during this recovery step."""
    if action_result.get("error"):
        return action_result["error"]
    for key in ("verify_result", "restart_result"):
        result = action_result.get(key)
        if isinstance(result, dict) and result.get("error"):
            return result["error"]
    return None


def build_action_signal(action_result):
    """Expose a recovery action without duplicating signal data or UI-only state."""
    action_taken = action_result.get("action", "none")
    if action_taken == "none":
        return {"taken": "none", "detail": None}

    detail = {
        key: value
        for key, value in action_result.items()
        if key not in {"action", "stream_index", "stream_status", "heartbeat"}
    }
    disconnect = detail.get("disconnect")
    if isinstance(disconnect, dict):
        # The event/action already describes the transition. Keep only facts
        # needed to measure and explain the disconnect episode.
        detail["disconnect"] = {
            key: value for key, value in disconnect.items() if key != "state"
        }
    return {"taken": action_taken, "detail": detail or None}


def build_recovery_event(report, action_result):
    """Create the optional recovery-feed entry for a non-idle stream check."""
    action = report.get("action", {}).get("taken")
    if action in (None, "none"):
        return None

    if action == "connection_restored":
        status = "succeeded"
    elif action in {"needs_action", "manual_stop"}:
        status = "needs_action"
    elif action in {
        "stopped_stream_waiting_for_reconnect",
        "unplug_detected",
        "filling_missing_samples",
        "heartbeat_age_exceeded",
        "waiting_for_port",
        "waiting_for_port_release",
        "waiting_for_heartbeat",
        "lifecycle_busy",
        "reconnect_failed_stop_stream_completed",
    }:
        status = "pending"
    else:
        status = "failed"

    detail = report.get("action", {}).get("detail") or {}
    return {
        "event_type": "stream_recovery",
        "stream_index": report.get("stream_index"),
        "checked_at": report.get("checked_at"),
        "port": report.get("port"),
        "action": action,
        "status": status,
        "stream_health": report.get("stream_health"),
        "failure_reason": action_result.get("failure_reason"),
        "initiating_failure_reason": action_result.get("initiating_failure_reason"),
        "failure_count": report.get("signals", {}).get("failure", {}).get("count"),
        "recovery_policy": action_result.get("recovery_policy", "recommend"),
        "recovery_attempt": action_result.get("recovery_attempt"),
        "requested_by": detail.get("requested_by"),
        "summary": report.get("summary"),
    }
