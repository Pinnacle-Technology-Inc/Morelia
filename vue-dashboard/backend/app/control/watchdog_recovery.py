"""Evidence-driven decisions for recovering a dead runtime host."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from app.config import get_config
from app.models.runtime_ownership import RuntimeOwnership
from app.runtime_host.manifest import Manifest
from app.runtime_host.watchdog_process_driver import _kill_pid, pid_is_alive
from app.watchdog_process.control import (
    WatchdogControlClient,
    WatchdogControlError,
)
from app.watchdog_process.hardware_lease import HardwareLeaseBusy, HardwareLeaseSet


class RecoveryAction(StrEnum):
    """The only safe actions after a runtime host is confirmed dead."""

    START_FRESH = "start_fresh"
    ADOPT = "adopt"
    STOP_THEN_FRESH = "stop_then_fresh"
    RETRY = "retry"


@dataclass(frozen=True, slots=True)
class WatchdogEvidence:
    """Evidence about the watchdog that may have survived its runtime host."""

    pid_alive: bool | None
    identity_verified: bool = False
    adoption_failed: bool = False


def decide_recovery(evidence: WatchdogEvidence) -> RecoveryAction:
    """Choose an action without turning missing evidence into proof of death."""
    if evidence.pid_alive is False:
        return RecoveryAction.START_FRESH
    if evidence.pid_alive is True and evidence.identity_verified:
        if evidence.adoption_failed:
            return RecoveryAction.STOP_THEN_FRESH
        return RecoveryAction.ADOPT
    return RecoveryAction.RETRY


@dataclass(frozen=True, slots=True)
class RecoveryAssessment:
    action: RecoveryAction
    reason: str
    evidence: dict[str, object]


class WatchdogRecoveryCoordinator:
    """Collect independent process, identity, and hardware-lease evidence."""

    def __init__(
        self,
        *,
        hardware_lock_dir: str | Path,
        pid_alive: Callable[[int], bool] = pid_is_alive,
        control_client_factory: Callable[..., WatchdogControlClient] = WatchdogControlClient,
        terminate_pid: Callable[[int], None] = _kill_pid,
    ) -> None:
        self._hardware_lock_dir = hardware_lock_dir
        self._pid_alive = pid_alive
        self._control_client_factory = control_client_factory
        self._terminate_pid = terminate_pid

    def assess(
        self, ownership: RuntimeOwnership, manifest: Manifest
    ) -> RecoveryAssessment:
        pid = ownership.watchdog_pid
        alive = self._pid_alive(pid) if pid is not None else None
        leases_free = self._leases_are_free(manifest)
        evidence: dict[str, object] = {
            "pid": pid,
            "pid_alive": alive,
            "hardware_leases_free": leases_free,
            "identity_verified": False,
        }

        if leases_free and (alive is False or (pid is None and ownership.watchdog_id is None)):
            return RecoveryAssessment(
                RecoveryAction.START_FRESH,
                "watchdog_dead_and_hardware_released",
                evidence,
            )

        if (
            ownership.watchdog_control_port is None
            or not ownership.token
            or not ownership.watchdog_id
        ):
            return RecoveryAssessment(
                RecoveryAction.RETRY,
                "authenticated_watchdog_control_unavailable"
                if alive is True
                else "watchdog_or_hardware_state_ambiguous",
                evidence,
            )

        client = self._control_client_factory(
            port=ownership.watchdog_control_port,
            token=ownership.token,
        )
        try:
            response = client.probe()
        except WatchdogControlError:
            return RecoveryAssessment(
                RecoveryAction.RETRY,
                "watchdog_authentication_probe_failed",
                evidence,
            )

        expected = {
            "watchdog_id": ownership.watchdog_id,
            "dataflow_id": ownership.dataflow_id,
            "manifest_hash": manifest.hash,
        }
        runtime_id = getattr(ownership, "runtime_id", None)
        if runtime_id is not None:
            expected["runtime_id"] = runtime_id
        stable_identity_verified = all(
            response.get(key) == value for key, value in expected.items()
        )
        probed_pid = response.get("pid")
        probed_pid_valid = (
            isinstance(probed_pid, int)
            and not isinstance(probed_pid, bool)
            and probed_pid > 0
        )
        probed_pid_alive = self._pid_alive(probed_pid) if probed_pid_valid else False
        identity_verified = stable_identity_verified and probed_pid_alive
        evidence["identity_verified"] = identity_verified
        evidence["control_port"] = ownership.watchdog_control_port
        evidence["probed_pid"] = probed_pid
        evidence["probed_pid_alive"] = probed_pid_alive
        if identity_verified:
            evidence["verified_pid"] = probed_pid
            evidence["pid_corrected"] = probed_pid != ownership.watchdog_pid
            return RecoveryAssessment(
                RecoveryAction.ADOPT,
                "watchdog_identity_verified_alive",
                evidence,
            )
        return RecoveryAssessment(
            RecoveryAction.RETRY,
            "watchdog_identity_mismatch"
            if not stable_identity_verified
            else "watchdog_pid_not_alive",
            evidence,
        )

    def stop_exact_watchdog(
        self,
        ownership: RuntimeOwnership,
        manifest: Manifest,
        *,
        recovery_id: str,
        timeout_seconds: float | None = None,
    ) -> bool:
        if timeout_seconds is None:
            timeout_seconds = get_config().WATCHDOG_PROCESS_STOP_TIMEOUT_SECONDS
        assessment = self.assess(ownership, manifest)
        if assessment.action is not RecoveryAction.ADOPT:
            return False
        target_pid = assessment.evidence.get("verified_pid")
        if (
            not isinstance(target_pid, int)
            or isinstance(target_pid, bool)
            or target_pid <= 0
        ):
            return False
        client = self._control_client_factory(
            port=ownership.watchdog_control_port,
            token=ownership.token,
        )
        try:
            client.stop_watchdog(recovery_id=recovery_id)
        except WatchdogControlError:
            return False
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            pid_dead = not self._pid_alive(target_pid)
            if pid_dead and self._leases_are_free(manifest):
                return True
            time.sleep(get_config().WATCHDOG_PROCESS_STOP_POLL_INTERVAL_SECONDS)
        try:
            response = client.probe()
        except WatchdogControlError:
            return False
        if (
            response.get("pid") != target_pid
            or response.get("watchdog_id") != ownership.watchdog_id
            or response.get("dataflow_id") != ownership.dataflow_id
            or response.get("manifest_hash") != manifest.hash
        ):
            return False
        self._terminate_pid(target_pid)
        deadline = time.monotonic() + get_config().WATCHDOG_RECOVERY_VERIFY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if not self._pid_alive(target_pid) and self._leases_are_free(manifest):
                return True
            time.sleep(get_config().WATCHDOG_PROCESS_STOP_POLL_INTERVAL_SECONDS)
        return False

    def _leases_are_free(self, manifest: Manifest) -> bool:
        leases = HardwareLeaseSet(manifest, directory=self._hardware_lock_dir)
        try:
            leases.acquire()
        except HardwareLeaseBusy:
            return False
        else:
            leases.release()
            return True


__all__ = [
    "RecoveryAction",
    "RecoveryAssessment",
    "WatchdogEvidence",
    "WatchdogRecoveryCoordinator",
    "decide_recovery",
]
