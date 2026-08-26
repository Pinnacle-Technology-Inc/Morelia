"""One operator-facing contract for stream recovery state and eligibility."""

from __future__ import annotations


WAITING_FOR_HARDWARE_ACTIONS = frozenset(
    {
        "unplug_detected",
        "filling_missing_samples",
        "heartbeat_age_exceeded",
        "waiting_for_port",
        "waiting_for_port_release",
    }
)


def project(
    *,
    action: object,
    stage: object,
    source_read_state: object = None,
    policy: object,
    hardware_present: object,
    controls_current: bool,
) -> dict[str, object]:
    """Return the bounded state the UI and command service both enforce."""
    action_name = action if isinstance(action, str) else None
    stage_name = stage if isinstance(stage, str) else None
    source_state = source_read_state if isinstance(source_read_state, str) else None
    policy_name = policy.value if hasattr(policy, "value") else policy
    policy_name = policy_name if isinstance(policy_name, str) else None
    if policy_name not in {"recommend", "automate"}:
        policy_name = "recommend"
    hardware = hardware_present if isinstance(hardware_present, bool) else None

    needs_action = action_name == "needs_action" or stage_name == "needs_action"
    if needs_action and hardware is False:
        state = "waiting_for_hardware"
    elif needs_action and policy_name == "recommend":
        state = "awaiting_approval"
    elif needs_action:
        state = "exhausted"
    elif action_name in WAITING_FOR_HARDWARE_ACTIONS and hardware is False:
        state = "waiting_for_hardware"
    elif action_name in WAITING_FOR_HARDWARE_ACTIONS:
        # The port may already be present while the data path is still settling
        # (for example, filling missing samples before real packets resume).
        state = "recovering"
    elif stage_name == "succeeded" or action_name == "connection_restored":
        state = "recovered"
    elif policy_name == "automate" and source_state in {
        "degraded",
        "recovery_window_expired",
    }:
        # Automate keeps reading, fills the gap, and reopens the source port
        # before the watchdog needs to restart the stream. That work is visible
        # first on the source-reader channel, so it must count as live recovery
        # even while the watchdog action is still idle.
        state = "recovering"
    elif stage_name in {"pending", "failed"} or action_name not in {None, "", "none"}:
        state = "recovering"
    else:
        state = "idle"

    requires_approval = policy_name == "recommend" and needs_action
    actionable_state = state in {"awaiting_approval", "exhausted"}
    allowed_actions = ["restart"] if controls_current and actionable_state else []
    return {
        "recovery_policy": policy_name,
        "recovery_state": state,
        "requires_approval": requires_approval,
        "hardware_present": hardware,
        "control_available": controls_current,
        "allowed_recovery_actions": allowed_actions,
    }
