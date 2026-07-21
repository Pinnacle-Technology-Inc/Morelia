from pathlib import Path
from types import SimpleNamespace

import pytest

from app.control.watchdog_recovery import (
    RecoveryAction,
    WatchdogEvidence,
    WatchdogRecoveryCoordinator,
    decide_recovery,
)
from app.domain.enums import PolicyMode, SinkType
from app.runtime_host.manifest import DeviceFlow, Manifest
from app.watchdog_process.hardware_lease import HardwareLeaseBusy, HardwareLeaseSet
from app.watchdog_process.control import (
    WatchdogControlAuthenticationError,
    WatchdogControlClient,
    WatchdogControlServer,
)
from app.watchdog_process.process import WatchdogIdentity


def _manifest(*, port: str = "COM3") -> Manifest:
    return Manifest(
        schema_version="1",
        dataflow_id="df-recovery",
        policy=PolicyMode.AUTOMATE,
        device_flows=(
            DeviceFlow(
                device_id="device-1",
                name="pod",
                nickname=None,
                hardware_id="pod-123",
                port=port,
                parameters={},
                sink_type=SinkType.CSV,
                sink_location="C:/data/recovery.csv",
            ),
        ),
    )


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        (WatchdogEvidence(pid_alive=False), RecoveryAction.START_FRESH),
        (
            WatchdogEvidence(pid_alive=True, identity_verified=True),
            RecoveryAction.ADOPT,
        ),
        (
            WatchdogEvidence(
                pid_alive=True,
                identity_verified=True,
                adoption_failed=True,
            ),
            RecoveryAction.STOP_THEN_FRESH,
        ),
        (WatchdogEvidence(pid_alive=True), RecoveryAction.RETRY),
        (WatchdogEvidence(pid_alive=None), RecoveryAction.RETRY),
    ],
)
def test_recovery_decision_never_fresh_starts_on_ambiguous_evidence(evidence, expected):
    assert decide_recovery(evidence) is expected


def test_hardware_lease_blocks_a_second_watchdog(tmp_path: Path):
    first = HardwareLeaseSet(_manifest(), directory=tmp_path)
    second = HardwareLeaseSet(_manifest(), directory=tmp_path)

    first.acquire()
    try:
        with pytest.raises(HardwareLeaseBusy, match="pod-123"):
            second.acquire()
    finally:
        first.release()

    second.acquire()
    second.release()


def test_multi_device_lease_rolls_back_when_any_device_is_busy(tmp_path: Path):
    first = HardwareLeaseSet(_manifest(port="COM3"), directory=tmp_path)
    first.acquire()

    com4 = _manifest(port="COM4").device_flows[0]
    com3 = _manifest(port="COM3").device_flows[0]
    manifest = Manifest(
        schema_version="1",
        dataflow_id="df-two",
        policy=PolicyMode.AUTOMATE,
        device_flows=(
            DeviceFlow.from_dict(
                {
                    **com4.to_dict(),
                    "device_id": "device-2",
                    "sink_location": "C:/data/recovery-2.csv",
                }
            ),
            DeviceFlow.from_dict(
                {
                    **com3.to_dict(),
                    "device_id": "device-3",
                    "sink_location": "C:/data/recovery-3.csv",
                }
            ),
        ),
    )
    contender = HardwareLeaseSet(manifest, directory=tmp_path)
    try:
        with pytest.raises(HardwareLeaseBusy):
            contender.acquire()
        assert contender.acquired is False
    finally:
        first.release()


class _ControllableProcess:
    def __init__(self):
        self.identity = WatchdogIdentity(runtime_id="runtime-old", watchdog_id="watchdog-1")
        self.manifest = _manifest()

    def rebind_runtime(self, runtime_id: str) -> None:
        self.identity = WatchdogIdentity(
            runtime_id=runtime_id,
            watchdog_id=self.identity.watchdog_id,
        )


def test_watchdog_control_channel_authenticates_probe_adopt_and_stop():
    process = _ControllableProcess()
    stopped = []
    server = WatchdogControlServer(
        process=process,
        token="control-secret",
        hardware_lease_keys=("pod-123@COM3",),
        request_stop=lambda: stopped.append(True),
    )
    server.start()
    try:
        client = WatchdogControlClient(port=server.port, token="control-secret")
        evidence = client.probe()
        assert evidence["watchdog_id"] == "watchdog-1"
        assert evidence["runtime_id"] == "runtime-old"
        assert evidence["manifest_hash"] == process.manifest.hash
        assert evidence["hardware_leases"] == ["pod-123@COM3"]

        client.adopt(new_runtime_id="runtime-new", recovery_id="recovery-1")
        assert process.identity.runtime_id == "runtime-new"

        client.stop_watchdog(recovery_id="recovery-1")
        assert stopped == [True]
    finally:
        server.stop()


def test_watchdog_control_channel_rejects_wrong_token():
    server = WatchdogControlServer(
        process=_ControllableProcess(),
        token="correct-token",
        hardware_lease_keys=(),
        request_stop=lambda: None,
    )
    server.start()
    try:
        with pytest.raises(WatchdogControlAuthenticationError):
            WatchdogControlClient(port=server.port, token="wrong-token").probe()
    finally:
        server.stop()


def test_recovery_coordinator_starts_fresh_only_after_pid_and_leases_are_free(tmp_path):
    ownership = SimpleNamespace(
        watchdog_pid=999,
        watchdog_id="watchdog-1",
        watchdog_control_port=None,
        token="token",
        dataflow_id="df-recovery",
    )
    coordinator = WatchdogRecoveryCoordinator(
        hardware_lock_dir=tmp_path,
        pid_alive=lambda _pid: False,
    )

    assessment = coordinator.assess(ownership, _manifest())

    assert assessment.action is RecoveryAction.START_FRESH
    assert assessment.evidence["hardware_leases_free"] is True


def test_recovery_coordinator_requires_authenticated_identity_for_adoption(tmp_path):
    manifest = _manifest()
    ownership = SimpleNamespace(
        watchdog_pid=999,
        watchdog_id="watchdog-1",
        watchdog_control_port=43210,
        token="token",
        dataflow_id=manifest.dataflow_id,
    )

    class _Client:
        def __init__(self, **_kwargs):
            pass

        def probe(self):
            return {
                "pid": 999,
                "watchdog_id": "watchdog-1",
                "dataflow_id": manifest.dataflow_id,
                "manifest_hash": manifest.hash,
            }

    coordinator = WatchdogRecoveryCoordinator(
        hardware_lock_dir=tmp_path,
        pid_alive=lambda _pid: True,
        control_client_factory=_Client,
    )

    assert coordinator.assess(ownership, manifest).action is RecoveryAction.ADOPT

    ownership.watchdog_control_port = None
    assert coordinator.assess(ownership, manifest).action is RecoveryAction.RETRY


def test_recovery_coordinator_repairs_pid_from_authenticated_stable_identity(tmp_path):
    manifest = _manifest()
    ownership = SimpleNamespace(
        watchdog_pid=999,
        watchdog_id="watchdog-1",
        watchdog_control_port=43210,
        token="token",
        dataflow_id=manifest.dataflow_id,
    )

    class _Client:
        def __init__(self, **_kwargs):
            pass

        def probe(self):
            return {
                "pid": 1000,
                "watchdog_id": "watchdog-1",
                "dataflow_id": manifest.dataflow_id,
                "manifest_hash": manifest.hash,
            }

    coordinator = WatchdogRecoveryCoordinator(
        hardware_lock_dir=tmp_path,
        pid_alive=lambda _pid: True,
        control_client_factory=_Client,
    )

    assessment = coordinator.assess(ownership, manifest)

    assert assessment.action is RecoveryAction.ADOPT
    assert assessment.evidence["verified_pid"] == 1000


def test_recovery_coordinator_does_not_repair_pid_when_stable_identity_mismatches(
    tmp_path,
):
    manifest = _manifest()
    ownership = SimpleNamespace(
        watchdog_pid=999,
        watchdog_id="watchdog-1",
        watchdog_control_port=43210,
        token="token",
        dataflow_id=manifest.dataflow_id,
    )

    class _Client:
        def __init__(self, **_kwargs):
            pass

        def probe(self):
            return {
                "pid": 1000,
                "watchdog_id": "different-watchdog",
                "dataflow_id": manifest.dataflow_id,
                "manifest_hash": manifest.hash,
            }

    coordinator = WatchdogRecoveryCoordinator(
        hardware_lock_dir=tmp_path,
        pid_alive=lambda _pid: True,
        control_client_factory=_Client,
    )

    assessment = coordinator.assess(ownership, manifest)

    assert assessment.action is RecoveryAction.RETRY
    assert "verified_pid" not in assessment.evidence


def test_recovery_coordinator_force_stops_only_reauthenticated_exact_watchdog(tmp_path):
    manifest = _manifest()
    alive = {"value": True}
    terminated = []
    ownership = SimpleNamespace(
        watchdog_pid=999,
        watchdog_id="watchdog-1",
        watchdog_control_port=43210,
        token="token",
        dataflow_id=manifest.dataflow_id,
    )

    class _Client:
        def __init__(self, **_kwargs):
            pass

        def probe(self):
            return {
                "pid": 999,
                "watchdog_id": "watchdog-1",
                "dataflow_id": manifest.dataflow_id,
                "manifest_hash": manifest.hash,
            }

        def stop_watchdog(self, **_kwargs):
            return {"status": "stopping"}

    def _terminate(pid):
        terminated.append(pid)
        alive["value"] = False

    coordinator = WatchdogRecoveryCoordinator(
        hardware_lock_dir=tmp_path,
        pid_alive=lambda _pid: alive["value"],
        control_client_factory=_Client,
        terminate_pid=_terminate,
    )

    assert coordinator.stop_exact_watchdog(
        ownership, manifest, recovery_id="recovery-1", timeout_seconds=0
    )
    assert terminated == [999]


def test_recovery_coordinator_force_stop_targets_authenticated_corrected_pid(tmp_path):
    manifest = _manifest()
    alive = {999, 1000}
    terminated = []
    ownership = SimpleNamespace(
        watchdog_pid=999,
        watchdog_id="watchdog-1",
        watchdog_control_port=43210,
        token="token",
        dataflow_id=manifest.dataflow_id,
    )

    class _Client:
        def __init__(self, **_kwargs):
            pass

        def probe(self):
            return {
                "pid": 1000,
                "watchdog_id": "watchdog-1",
                "dataflow_id": manifest.dataflow_id,
                "manifest_hash": manifest.hash,
            }

        def stop_watchdog(self, **_kwargs):
            return {"status": "stopping"}

    def _terminate(pid):
        terminated.append(pid)
        alive.discard(pid)

    coordinator = WatchdogRecoveryCoordinator(
        hardware_lock_dir=tmp_path,
        pid_alive=lambda pid: pid in alive,
        control_client_factory=_Client,
        terminate_pid=_terminate,
    )

    assert coordinator.stop_exact_watchdog(
        ownership, manifest, recovery_id="recovery-1", timeout_seconds=0
    )
    assert terminated == [1000]
