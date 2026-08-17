"""Contract tests for the versioned Flask-to-Watchdog HTTP boundary."""

from dataclasses import dataclass

import pytest

import app.services.sessions as session_service
from app import create_app
from app.database import db
from app.domain.enums import DeviceType, PolicyMode, SessionStatus, SinkType
from app.runtime_child.driver import RuntimePhase
from app.runtime_host.lifecycle import LifecycleSafetyGate
from app.runtime_host.manifest import MANIFEST_SCHEMA_VERSION, DeviceFlow, Manifest
from app.services.device_configs import create as create_device_config
from app.watchdog.adapters import (
    ControlPlaneCommandSender,
    WatchdogHttpResponse,
    WatchdogInvalidResponseError,
    WatchdogTimeoutError,
    WatchdogUnavailableError,
    WatchdogUnsupportedProtocolError,
)
from app.watchdog.messages import (
    WATCHDOG_COMMAND_PATH,
    WATCHDOG_PROTOCOL_VERSION,
    CommandEnvelope,
    CorrelationEnvelope,
)


@dataclass
class StubTransport:
    response: WatchdogHttpResponse | None = None
    error: Exception | None = None

    def __post_init__(self):
        self.requests = []

    def post_json(self, *, url, payload, timeout_seconds, max_response_bytes):
        self.requests.append(
            {
                "url": url,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
                "max_response_bytes": max_response_bytes,
            }
        )
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def _valid_flow():
    config = create_device_config(
        device_type=DeviceType.POD8206HR,
        hardware_id="001",
        port="COM3",
        parameters={"preamp_gain": 10},
    )
    return {
        "device_config_id": config.id,
        "sink_type": "csv",
        "sink_location": "C:/data/watchdog.csv",
    }


@pytest.fixture
def command():
    return CommandEnvelope(
        command="restart",
        correlation=CorrelationEnvelope(
            request_id="request-1",
            dataflow_id="dataflow-1",
            command_id="command-1",
            watchdog_id="watchdog-1",
        ),
    )


def test_success_uses_versioned_request_and_validates_correlated_acknowledgement(command):
    transport = StubTransport(
        response=WatchdogHttpResponse.json(
            status_code=202,
            payload={
                "protocol_version": WATCHDOG_PROTOCOL_VERSION,
                "status": "accepted",
                "command_id": "command-1",
                "watchdog_id": "watchdog-1",
            },
        )
    )
    sender = ControlPlaneCommandSender(
        base_url="http://127.0.0.1:8765",
        timeout_seconds=1.5,
        transport=transport,
    )

    acknowledgement = sender.dispatch(command)

    assert acknowledgement.status == "accepted"
    assert transport.requests == [
        {
            "url": f"http://127.0.0.1:8765{WATCHDOG_COMMAND_PATH}",
            "payload": {
                "protocol_version": WATCHDOG_PROTOCOL_VERSION,
                "command": "restart",
                "correlation": {
                    "request_id": "request-1",
                    "dataflow_id": "dataflow-1",
                    "command_id": "command-1",
                    "watchdog_id": "watchdog-1",
                },
            },
            "timeout_seconds": 1.5,
            "max_response_bytes": 65_536,
        }
    ]


def test_timeout_is_reported_as_a_safe_typed_failure(command):
    sender = ControlPlaneCommandSender(
        base_url="http://127.0.0.1:8765",
        transport=StubTransport(error=TimeoutError()),
    )

    with pytest.raises(WatchdogTimeoutError, match="timed out"):
        sender.dispatch(command)


def test_malformed_response_is_rejected_before_backend_uses_it(command):
    sender = ControlPlaneCommandSender(
        base_url="http://127.0.0.1:8765",
        transport=StubTransport(
            response=WatchdogHttpResponse(
                status_code=202,
                content_type="application/json",
                body=b'{"protocol_version": "1", "status":',
            )
        ),
    )

    with pytest.raises(WatchdogInvalidResponseError, match="invalid JSON"):
        sender.dispatch(command)


def test_unsupported_response_version_is_rejected(command):
    sender = ControlPlaneCommandSender(
        base_url="http://127.0.0.1:8765",
        transport=StubTransport(
            response=WatchdogHttpResponse.json(
                status_code=202,
                payload={
                    "protocol_version": "2",
                    "status": "accepted",
                    "command_id": "command-1",
                    "watchdog_id": "watchdog-1",
                },
            )
        ),
    )

    with pytest.raises(WatchdogUnsupportedProtocolError, match="unsupported"):
        sender.dispatch(command)


def test_unavailable_watchdog_is_reported_as_a_safe_typed_failure(command):
    sender = ControlPlaneCommandSender(
        base_url="http://127.0.0.1:8765",
        transport=StubTransport(error=ConnectionRefusedError()),
    )

    with pytest.raises(WatchdogUnavailableError, match="unavailable"):
        sender.dispatch(command)


@pytest.mark.parametrize(
    "base_url",
    [
        "https://127.0.0.1:8765",
        "http://watchdog.example:8765",
        "http://127.0.0.1:not-a-port",
        "http://127.0.0.1:8765/prefix",
    ],
)
def test_command_sender_rejects_urls_outside_the_local_v1_contract(base_url):
    with pytest.raises(ValueError, match="localhost"):
        ControlPlaneCommandSender(base_url=base_url)


class _StubWatchdogSupervisingDriver:
    """Minimal driver stub exposing an active ``watchdog_id`` (packet 06/07).

    Only what ``LifecycleSafetyGate.accept`` touches before rejecting a stale
    command: ``phase`` and ``watchdog_id``. Driver work (``preflight``/
    ``start``/``stop``/``recover``) is never reached once fencing rejects the
    envelope, so those are left unimplemented.
    """

    def __init__(self, *, watchdog_id: str | None) -> None:
        self.watchdog_id = watchdog_id
        self.phase = RuntimePhase.RUNNING
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _PreflightedStartDriver:
    """Driver already preflighted by runtime-host startup."""

    phase = RuntimePhase.PREFLIGHT
    watchdog_id = "watchdog-active"

    def __init__(self) -> None:
        self.started = False

    def preflight(self) -> None:
        raise AssertionError("start must not repeat runtime-host preflight")

    def start(self) -> None:
        self.started = True
        self.phase = RuntimePhase.RUNNING


def _stale_watchdog_manifest() -> Manifest:
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        dataflow_id="dataflow-stale-watchdog",
        policy=PolicyMode.RECOMMEND,
        device_flows=(
            DeviceFlow(
                device_id="dev-stale-watchdog",
                name="device-stale-watchdog",
                nickname=None,
                hardware_id="002",
                port="usb-1",
                parameters={},
                sink_type=SinkType.CSV,
                sink_location="/data/dev-stale-watchdog.csv",
            ),
        ),
    )


def _stop_envelope(*, watchdog_id: str) -> CommandEnvelope:
    return CommandEnvelope(
        command="stop",
        correlation=CorrelationEnvelope(
            request_id="request-1",
            dataflow_id="dataflow-stale-watchdog",
            command_id="command-1",
            watchdog_id=watchdog_id,
        ),
    )


def _start_envelope(*, watchdog_id: str) -> CommandEnvelope:
    return CommandEnvelope(
        command="start",
        correlation=CorrelationEnvelope(
            request_id="request-start",
            dataflow_id="dataflow-stale-watchdog",
            command_id="command-start",
            watchdog_id=watchdog_id,
        ),
    )


def test_preflighted_runtime_host_start_does_not_repeat_preflight():
    driver = _PreflightedStartDriver()
    gate = LifecycleSafetyGate(manifest=_stale_watchdog_manifest(), driver=driver)

    acknowledgement = gate.handle(_start_envelope(watchdog_id="watchdog-active").to_dict())

    assert acknowledgement.status == "accepted"
    assert driver.started is True


class TestLifecycleGateStaleWatchdogFencing:
    """Packet 07 — runtime host must reject a command naming a stale
    watchdog_id before forwarding it to the (no longer active) watchdog."""

    def test_command_targeting_a_stale_watchdog_id_is_rejected(self):
        driver = _StubWatchdogSupervisingDriver(watchdog_id="watchdog-active")
        gate = LifecycleSafetyGate(manifest=_stale_watchdog_manifest(), driver=driver)

        with pytest.raises(ValueError, match="stale watchdog_id"):
            gate.accept(_stop_envelope(watchdog_id="watchdog-stale").to_dict())

    def test_command_targeting_the_active_watchdog_id_is_accepted(self):
        driver = _StubWatchdogSupervisingDriver(watchdog_id="watchdog-active")
        gate = LifecycleSafetyGate(manifest=_stale_watchdog_manifest(), driver=driver)

        envelope, run = gate.accept(_stop_envelope(watchdog_id="watchdog-active").to_dict())
        run()

        assert envelope.correlation.watchdog_id == "watchdog-active"
        assert driver.stopped is True

    def test_fencing_is_a_no_op_before_any_watchdog_process_is_active(self):
        """A driver that hasn't spawned/adopted a watchdog yet (fresh IDLE,
        or a driver flavor with no separate watchdog process at all) has
        nothing to be stale relative to — the command proceeds unfenced."""
        driver = _StubWatchdogSupervisingDriver(watchdog_id=None)
        gate = LifecycleSafetyGate(manifest=_stale_watchdog_manifest(), driver=driver)

        envelope, run = gate.accept(_stop_envelope(watchdog_id="anything").to_dict())

        assert envelope.correlation.watchdog_id == "anything"

    def test_stale_watchdog_rejection_happens_before_the_command_in_flight_lock(self):
        """Fencing is a cheap, synchronous validation — it must reject before
        acquiring the scope lock, so a stale command never blocks a
        legitimate one from the active watchdog."""
        driver = _StubWatchdogSupervisingDriver(watchdog_id="watchdog-active")
        gate = LifecycleSafetyGate(manifest=_stale_watchdog_manifest(), driver=driver)

        with pytest.raises(ValueError, match="stale watchdog_id"):
            gate.accept(_stop_envelope(watchdog_id="watchdog-stale").to_dict())

        # The scope lock was never acquired by the rejected command, so a
        # legitimate command against the active watchdog still succeeds.
        envelope, run = gate.accept(_stop_envelope(watchdog_id="watchdog-active").to_dict())
        assert envelope.correlation.watchdog_id == "watchdog-active"
