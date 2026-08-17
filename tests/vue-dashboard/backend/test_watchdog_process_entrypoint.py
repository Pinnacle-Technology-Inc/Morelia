"""Tests for the watchdog-process entrypoint, orchestration, and telemetry client.

Per the packet's scope boundary, no real Morelia hardware is used: driver
tests use a local stub with the same lifecycle methods as ``MoreliaRuntime``.
The ``--driver morelia`` wiring itself is exercised only up to *constructing*
``MoreliaRuntime`` (which is lazy and does not import Morelia — see
``app.runtime_child.morelia``), never ``preflight()``/``start()``.

Telemetry delivery is tested two ways:
- Pure unit tests of ``WatchdogProcess`` against a fake ``TelemetryClient``
  transport (fast, no Flask).
- Contract tests of ``TelemetryClient`` against the real
  ``POST /api/v1/internal/events`` endpoint via the `app`/`client` fixtures,
  proving the client's status-code classification matches the real ingest
  contract's fencing/validation responses (mirrors
  ``tests/test_event_push_contract.py``'s style).
"""

from __future__ import annotations

import json

import pytest

from app.database import transaction
from app.domain.enums import CommsStatus, PolicyMode, SinkType, StreamStatus
from app.repositories.runtime_ownership import RuntimeOwnershipRepository
from app.repositories.sessions import SessionRepository
from app.runtime_child.driver import (
    DeviceReport,
    RuntimePhase,
    RuntimeReport,
    SinkDeliveryState,
    SinkHealth,
    SinkReport,
)
from app.runtime_child.morelia import MoreliaRuntime
from app.runtime_host.manifest import MANIFEST_SCHEMA_VERSION, DeviceFlow, Manifest
from app.watchdog_process import __main__ as entrypoint
from app.watchdog_process.outbox import WatchdogOutbox
from app.watchdog_process.process import WatchdogIdentity, WatchdogProcess
from app.watchdog_process.telemetry_client import DeliveryOutcome, TelemetryClient

# ── Shared helpers ────────────────────────────────────────────────────────────


def _device_flow(device_id: str = "dev-a") -> DeviceFlow:
    return DeviceFlow(
        device_id=device_id,
        name=f"device-{device_id}",
        nickname=None,
        hardware_id=f"hw-{device_id}",
        port="usb-1",
        parameters={"sample_rate": 250},
        sink_type=SinkType.CSV,
        sink_location=f"/data/{device_id}.csv",
    )


def _manifest(dataflow_id: str = "df-1") -> Manifest:
    # Use the current manifest schema version: hand-constructing a legacy
    # schema_version="1" object and round-tripping it through to_dict() is not a
    # supported path (v1 exists only as inbound wire, normalized to v2 on read —
    # see Manifest.from_dict). build_process() writes/reads this manifest, so it
    # must be a native current-version manifest.
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        dataflow_id=dataflow_id,
        policy=PolicyMode.RECOMMEND,
        device_flows=(_device_flow(),),
    )


def _report(manifest: Manifest, *, sequence: int = 0) -> RuntimeReport:
    return RuntimeReport(
        dataflow_id=manifest.dataflow_id,
        phase=RuntimePhase.RUNNING,
        comms=CommsStatus.CURRENT,
        devices=tuple(
            DeviceReport(device_id=df.device_id, stream_status=StreamStatus.HEALTHY)
            for df in manifest.device_flows
        ),
        sequence=sequence,
    )


def _sink_report(
    *,
    sink_id: str = "dev-a:csv",
    source_id: str = "dev-a",
    sink_class: str = "csv",
    health: SinkHealth = SinkHealth.HEALTHY,
    delivery: SinkDeliveryState = SinkDeliveryState.DELIVERED,
    sequence: int = 0,
    state_timestamp_ns: int = 1_700_000_000_000_000_000,
    **overrides: object,
) -> SinkReport:
    values: dict[str, object] = {
        "sink_id": sink_id,
        "source_id": source_id,
        "sink_class": sink_class,
        "health": health,
        "delivery": delivery,
        "sequence": sequence,
        "state_timestamp_ns": state_timestamp_ns,
    }
    values.update(overrides)
    return SinkReport(**values)  # type: ignore[arg-type]


def _report_with_sinks(manifest: Manifest, *, sequence: int = 0, sinks=()) -> RuntimeReport:
    return RuntimeReport(
        dataflow_id=manifest.dataflow_id,
        phase=RuntimePhase.RUNNING,
        comms=CommsStatus.CURRENT,
        devices=tuple(
            DeviceReport(device_id=df.device_id, stream_status=StreamStatus.HEALTHY)
            for df in manifest.device_flows
        ),
        sequence=sequence,
        sinks=tuple(sinks),
    )


class StubDriver:
    """Minimal ``MoreliaRuntime`` stand-in — no hardware, no threads.

    ``emit`` lets a test manually trigger a report through the same
    ``on_report`` callback a real driver would use, without any of
    Morelia's threading/hardware machinery.
    """

    def __init__(self, *, manifest: Manifest, on_report) -> None:
        self.manifest = manifest
        self.on_report = on_report
        self._phase = RuntimePhase.IDLE
        self.stop_calls = 0
        self.close_calls = 0

    @property
    def phase(self) -> RuntimePhase:
        return self._phase

    def preflight(self) -> None:
        self._phase = RuntimePhase.PREFLIGHT

    def start(self) -> None:
        self._phase = RuntimePhase.RUNNING

    def stop(self) -> None:
        self.stop_calls += 1
        self._phase = RuntimePhase.STOPPED

    def close(self) -> None:
        self.close_calls += 1
        self._phase = RuntimePhase.CLOSED

    def recover(self, recovery_id: str, device_id: str) -> None:
        raise NotImplementedError

    def emit(self, report: RuntimeReport) -> None:
        self.on_report(report)


class ImmediateReportStubDriver(StubDriver):
    """Like StubDriver, but start() synchronously emits one report.

    Simulates a real driver whose watchdog loop reports immediately after
    start(), without needing an actual background thread in tests.
    """

    def start(self) -> None:
        super().start()
        self.emit(_report(self.manifest, sequence=0))


def _identity(**overrides) -> WatchdogIdentity:
    values = {"runtime_id": "rt-1", "watchdog_id": "wd-1"}
    values.update(overrides)
    return WatchdogIdentity(**values)


def _fake_client(transport) -> TelemetryClient:
    return TelemetryClient(base_url="http://plane.internal", transport=transport)


def _process(
    tmp_path,
    *,
    transport,
    manifest: Manifest | None = None,
    identity: WatchdogIdentity | None = None,
    build_driver=StubDriver,
    **process_kwargs,
) -> tuple[WatchdogProcess, WatchdogOutbox]:
    outbox = WatchdogOutbox(tmp_path / "wd.sqlite3")
    process = WatchdogProcess(
        manifest=manifest or _manifest(),
        identity=identity or _identity(),
        outbox=outbox,
        telemetry_client=_fake_client(transport),
        build_driver=build_driver,
        **process_kwargs,
    )
    return process, outbox


def _session_with_active_watchdog(
    app,
    *,
    dataflow_id: str,
    runtime_id: str,
    watchdog_id: str,
    manifest_hash: str,
) -> int:
    """Register a session + runtime ownership row with an active watchdog_id.

    Mirrors how the control plane's identity model (packet 02/03) expects a
    watchdog process to be recognized before its telemetry is accepted.
    """
    with app.app_context():
        session = SessionRepository().create({"name": "Watchdog Entrypoint Test"})
        with transaction():
            session.dataflow_id = dataflow_id
        RuntimeOwnershipRepository().create_starting(
            runtime_id=runtime_id,
            session_id=session.id,
            dataflow_id=dataflow_id,
            manifest_hash=manifest_hash,
            token=None,
        )
        RuntimeOwnershipRepository().set_watchdog(runtime_id, watchdog_id=watchdog_id)
        return session.id


def _client_transport(flask_client):
    """Adapt a Flask test client to TelemetryClient's TransportFn seam.

    Same idea as DataflowRuntimeHost's ``_push_fn`` testing seam
    (app/runtime_host/server.py) / FakePush (test_event_push_contract.py):
    the real ingest route runs, just without a live socket.
    """

    def _transport(envelope: dict, headers: dict[str, str]) -> tuple[int, dict | None]:
        resp = flask_client.post("/api/v1/internal/events", json=envelope, headers=headers)
        return resp.status_code, resp.get_json(silent=True)

    return _transport


# ── Acceptance criterion 1: load a manifest and initialize with runtime_id, ──
# ── watchdog_id, token, ingest URL, and outbox path ───────────────────────────


def test_argument_parser_accepts_all_required_identity_and_ingest_flags():
    parser = entrypoint.build_arg_parser()

    args = parser.parse_args(
        [
            "--manifest",
            "manifest.json",
            "--runtime-id",
            "rt-1",
            "--watchdog-id",
            "wd-1",
            "--ingest-url",
            "http://plane.internal",
            "--ingest-token",
            "secret-token",
        ]
    )

    assert args.manifest == "manifest.json"
    assert args.runtime_id == "rt-1"
    assert args.watchdog_id == "wd-1"
    assert args.ingest_url == "http://plane.internal"
    assert args.ingest_token == "secret-token"


@pytest.mark.parametrize(
    "missing_flag",
    ["--manifest", "--runtime-id", "--watchdog-id", "--ingest-url"],
)
def test_argument_parser_requires_identity_and_ingest_flags(missing_flag):
    full_argv = [
        "--manifest",
        "manifest.json",
        "--runtime-id",
        "rt-1",
        "--watchdog-id",
        "wd-1",
        "--ingest-url",
        "http://plane.internal",
    ]
    # Drop the flag under test and its value.
    idx = full_argv.index(missing_flag)
    argv = full_argv[:idx] + full_argv[idx + 2 :]

    with pytest.raises(SystemExit):
        entrypoint.build_arg_parser().parse_args(argv)


def test_build_process_loads_manifest_and_wires_identity_and_outbox_path(tmp_path):
    manifest = _manifest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest.to_dict()))
    outbox_dir = tmp_path / "outboxes"

    args = entrypoint.build_arg_parser().parse_args(
        [
            "--manifest",
            str(manifest_path),
            "--runtime-id",
            "rt-1",
            "--watchdog-id",
            "wd-1",
            "--ingest-url",
            "http://plane.internal",
            "--ingest-token",
            "tok-1",
            "--outbox-dir",
            str(outbox_dir),
        ]
    )

    process = entrypoint.build_process(args)
    try:
        assert isinstance(process.driver, MoreliaRuntime)
        assert process.outbox.path == outbox_dir / "wd-1.sqlite3"
        assert process.outbox.path.exists()
    finally:
        process.outbox.close()


def test_build_process_derives_outbox_path_from_configured_default_dir(tmp_path, monkeypatch):
    from app.config import Config

    class _StubConfig(Config):
        # Every other setting build_process/_build_driver consume is inherited
        # from the real Config so this stub can't silently drift from the
        # settings production actually reads.
        WATCHDOG_OUTBOX_DIR = str(tmp_path / "configured-outboxes")

    monkeypatch.setattr(entrypoint, "get_config", lambda: _StubConfig)

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest().to_dict()))

    args = entrypoint.build_arg_parser().parse_args(
        [
            "--manifest",
            str(manifest_path),
            "--runtime-id",
            "rt-1",
            "--watchdog-id",
            "wd-2",
            "--ingest-url",
            "http://plane.internal",
        ]
    )

    process = entrypoint.build_process(args)
    try:
        assert process.outbox.path == tmp_path / "configured-outboxes" / "wd-2.sqlite3"
    finally:
        process.outbox.close()


def test_build_process_threads_picklable_sink_delivery_outbox_factory(tmp_path, monkeypatch):
    """build_process wires a stable per-dataflow, picklable, path-based
    SinkDeliveryOutbox factory into MoreliaRuntime so _runtime_context can place
    it on RuntimeContext for the Influx/Quest worker builders. It is derived from
    SINK_DELIVERY_OUTBOX_DIR + dataflow_id and is kept separate from (and never
    conflated with) the telemetry WatchdogOutbox."""
    import functools
    import pickle

    from app.config import Config
    from app.domain.enums import DeviceType
    from app.runtime_child.morelia import open_sink_delivery_outbox, resolve_secret_from_env
    from app.watchdog_process.sink_delivery_outbox import (
        SinkDeliveryOutbox,
        default_sink_delivery_outbox_path,
    )

    class _StubConfig(Config):
        WATCHDOG_OUTBOX_DIR = str(tmp_path / "telemetry-outboxes")
        SINK_DELIVERY_OUTBOX_DIR = str(tmp_path / "sink-delivery")

    monkeypatch.setattr(entrypoint, "get_config", lambda: _StubConfig)

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest().to_dict()))

    args = entrypoint.build_arg_parser().parse_args(
        [
            "--manifest",
            str(manifest_path),
            "--runtime-id",
            "rt-1",
            "--watchdog-id",
            "wd-sink",
            "--ingest-url",
            "http://plane.internal",
        ]
    )

    process = entrypoint.build_process(args)
    try:
        driver = process.driver
        assert isinstance(driver, MoreliaRuntime)

        device_flow = process.manifest.device_flows[0]
        ctx = driver._runtime_context(object, device_flow, DeviceType.POD8206HR, pod=object())

        # The factory is a module-level partial (picklable by reference) — it must
        # be, since it crosses into the DataFlow worker via each sink's get_dict().
        factory = ctx.sink_delivery_outbox_factory
        assert isinstance(factory, functools.partial)
        assert factory.func is open_sink_delivery_outbox
        pickle.loads(pickle.dumps(factory))
        assert ctx.secret_resolver is resolve_secret_from_env

        expected_path = default_sink_delivery_outbox_path(
            str(tmp_path / "sink-delivery"), "df-1"
        )
        # Distinct from the telemetry outbox and stable across watchdog respawn.
        assert str(expected_path) == factory.args[0]
        assert process.outbox.path != expected_path

        outbox = factory()
        try:
            assert isinstance(outbox, SinkDeliveryOutbox)
            assert expected_path.exists()
        finally:
            outbox.close()
    finally:
        process.outbox.close()


def test_build_process_honors_explicit_outbox_path_override(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest().to_dict()))
    explicit_path = tmp_path / "explicit" / "custom.sqlite3"

    args = entrypoint.build_arg_parser().parse_args(
        [
            "--manifest",
            str(manifest_path),
            "--runtime-id",
            "rt-1",
            "--watchdog-id",
            "wd-3",
            "--ingest-url",
            "http://plane.internal",
            "--outbox-path",
            str(explicit_path),
            "--outbox-dir",
            str(tmp_path / "ignored-dir"),
        ]
    )

    process = entrypoint.build_process(args)
    try:
        assert process.outbox.path == explicit_path
    finally:
        process.outbox.close()


def test_telemetry_client_sends_configured_token_header():
    from app.contracts.watchdog_process_protocol import WatchdogTelemetryEnvelope

    captured = {}

    def _transport(envelope, headers):
        captured["headers"] = headers
        return 202, {"event_id": 1}

    client = TelemetryClient(base_url="http://plane.internal", token="my-token", transport=_transport)
    manifest = _manifest()
    envelope = WatchdogTelemetryEnvelope(
        report_id="wd-1:0",
        dataflow_id="df-1",
        runtime_id="rt-1",
        watchdog_id="wd-1",
        manifest_hash=manifest.hash,
        event_type="runtime.report",
        payload={"devices": []},
    )

    client.send(envelope)

    assert captured["headers"]["X-Agent-Token"] == "my-token"


# ── Acceptance criterion 2: reports are written to the outbox before flush ───
# ── attempts ───────────────────────────────────────────────────────────────────


def test_report_is_durably_enqueued_before_a_delivery_attempt_is_made(tmp_path):
    seen_pending_at_send_time = []

    def _transport(envelope, headers):
        pending_ids = {row.envelope.report_id for row in outbox.pending()}
        seen_pending_at_send_time.append(envelope["report_id"] in pending_ids)
        return 202, {"event_id": 1}

    process, outbox = _process(tmp_path, transport=_transport)

    process.driver.emit(_report(process.driver.manifest, sequence=0))

    assert seen_pending_at_send_time == [True]


def test_delivered_report_is_marked_delivered_and_no_longer_pending(tmp_path):
    process, outbox = _process(tmp_path, transport=lambda envelope, headers: (202, {"event_id": 1}))

    process.driver.emit(_report(process.driver.manifest, sequence=0))

    assert outbox.pending() == []


def test_retryable_transport_failure_leaves_report_pending_and_process_running(tmp_path):
    process, outbox = _process(tmp_path, transport=lambda envelope, headers: (0, None))

    process.driver.emit(_report(process.driver.manifest, sequence=0))

    assert process.stopped is False
    assert len(outbox.pending()) == 1


def test_rejected_400_leaves_report_pending_but_does_not_stop_the_process(tmp_path):
    process, outbox = _process(
        tmp_path, transport=lambda envelope, headers: (400, {"message": "manifest_hash mismatch"})
    )

    process.driver.emit(_report(process.driver.manifest, sequence=0))

    assert process.stopped is False
    assert len(outbox.pending()) == 1


def test_flush_preserves_order_stopping_at_first_non_delivered_report(tmp_path):
    delivered = []

    def _transport(envelope, headers):
        if envelope["report_id"].endswith(":0"):
            delivered.append(envelope["report_id"])
            return 202, {"event_id": 1}
        return 0, None  # sequence 1 fails; sequence 2 must not be attempted yet

    process, outbox = _process(tmp_path, transport=_transport)

    process.driver.emit(_report(process.driver.manifest, sequence=0))
    process.driver.emit(_report(process.driver.manifest, sequence=1))
    process.driver.emit(_report(process.driver.manifest, sequence=2))

    assert delivered == ["wd-1:0"]
    pending_ids = [row.envelope.report_id for row in outbox.pending()]
    assert pending_ids == ["wd-1:1", "wd-1:2"]


# ── Acceptance criterion 3: a stale/unauthorized ingest response stops the ───
# ── watchdog process — EXCEPT a 409 before the first acceptance, which is ────
# ── the identity-registration race and must be retried, not fatal ────────────


def test_stale_409_after_first_acceptance_flags_the_process_stopped(tmp_path):
    """A 409 after this watchdog has been accepted = real supersession → stop."""
    calls = {"n": 0}

    def _transport(envelope, headers):
        calls["n"] += 1
        if calls["n"] == 1:
            return 202, {"event_id": 1}
        return 409, {"message": "stale watchdog"}

    process, _outbox = _process(tmp_path, transport=_transport)

    process.driver.emit(_report(process.driver.manifest, sequence=0))
    assert process.stopped is False

    process.driver.emit(_report(process.driver.manifest, sequence=1))
    assert process.stopped is True
    assert process.stop_reason == "stale watchdog"


def test_stale_409_before_first_acceptance_is_retried_not_fatal(tmp_path):
    """Report :0 leaves the driver before the supervisor's poller can register
    the new watchdog_id from /status — that first 409 is the registration
    race, not fencing, and must leave the report pending for the next flush."""
    responses = iter([(409, {"message": "stale"}), (202, {"event_id": 1})])
    process, outbox = _process(
        tmp_path, transport=lambda envelope, headers: next(responses)
    )

    process.driver.emit(_report(process.driver.manifest, sequence=0))

    assert process.stopped is False
    assert len(outbox.pending()) == 1  # still pending, will be retried

    process.flush()  # identity registered by now — delivery goes through

    assert process.stopped is False
    assert outbox.pending() == []


def test_stale_streak_beyond_grace_budget_is_fatal(tmp_path):
    """A watchdog that is NEVER accepted must still give up eventually —
    otherwise a genuinely superseded process would hold the COM ports forever."""
    process, _outbox = _process(
        tmp_path,
        transport=lambda envelope, headers: (409, {"message": "stale"}),
        stale_grace_attempts=3,
    )

    process.driver.emit(_report(process.driver.manifest, sequence=0))  # streak 1
    process.flush()  # streak 2
    assert process.stopped is False

    process.flush()  # streak 3 — budget exhausted

    assert process.stopped is True
    assert process.stop_reason == "stale"


def test_unauthorized_401_response_flags_the_process_stopped(tmp_path):
    process, _outbox = _process(
        tmp_path, transport=lambda envelope, headers: (401, {"message": "invalid token"})
    )

    process.driver.emit(_report(process.driver.manifest, sequence=0))

    assert process.stopped is True
    assert process.stop_reason == "invalid token"


def test_fatal_response_does_not_synchronously_stop_the_driver(tmp_path):
    """_handle_fatal must not call shutdown() itself — see process.py's docstring
    on the self-join hazard with a real driver's watchdog thread."""
    process, _outbox = _process(
        tmp_path, transport=lambda envelope, headers: (401, {"message": "invalid token"})
    )
    process.driver.start()

    process.driver.emit(_report(process.driver.manifest, sequence=0))

    assert process.stopped is True
    assert process.driver.stop_calls == 0
    assert process.driver.close_calls == 0


def test_shutdown_after_fatal_stops_and_closes_the_driver(tmp_path):
    process, _outbox = _process(
        tmp_path, transport=lambda envelope, headers: (401, {"message": "invalid token"})
    )
    process.driver.start()
    process.driver.emit(_report(process.driver.manifest, sequence=0))
    assert process.stopped is True

    process.shutdown()

    assert process.driver.stop_calls == 1
    assert process.driver.close_calls == 1
    assert process.driver.phase is RuntimePhase.CLOSED


def test_shutdown_is_idempotent(tmp_path):
    process, _outbox = _process(tmp_path, transport=lambda envelope, headers: (202, {}))
    process.driver.start()

    process.shutdown()
    process.shutdown()

    assert process.driver.stop_calls == 1  # phase left STOPPABLE_PHASES after the first call
    assert process.driver.close_calls == 2  # close() itself is documented idempotent


def test_main_returns_exit_code_1_after_a_fatal_ingest_rejection(tmp_path):
    manifest = _manifest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest.to_dict()))

    def _factory(args):
        outbox = WatchdogOutbox(tmp_path / "wd.sqlite3")
        client = TelemetryClient(
            base_url=args.ingest_url,
            # 401, not 409: a 409 before first acceptance is now retried (the
            # registration-race grace), so it would never stop this stub.
            transport=lambda envelope, headers: (401, {"message": "invalid token"}),
        )
        return WatchdogProcess(
            manifest=manifest,
            identity=WatchdogIdentity(
                runtime_id=args.runtime_id,
                watchdog_id=args.watchdog_id,
            ),
            outbox=outbox,
            telemetry_client=client,
            build_driver=ImmediateReportStubDriver,
        )

    argv = [
        "--manifest",
        str(manifest_path),
        "--runtime-id",
        "rt-1",
        "--watchdog-id",
        "wd-1",
        "--ingest-url",
        "http://plane.internal",
    ]

    exit_code = entrypoint.main(
        argv,
        process_factory=_factory,
        process_tree_guard_factory=lambda: None,
        poll_interval_seconds=0.01,
    )

    assert exit_code == 1


def test_main_returns_exit_code_0_when_never_stopped(tmp_path, monkeypatch):
    """Simulates a clean SIGINT/SIGTERM shutdown: the stop_event fires before
    any fatal outcome occurs."""
    manifest = _manifest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest.to_dict()))

    def _factory(args):
        outbox = WatchdogOutbox(tmp_path / "wd.sqlite3")
        client = TelemetryClient(
            base_url=args.ingest_url,
            transport=lambda envelope, headers: (202, {"event_id": 1}),
        )
        return WatchdogProcess(
            manifest=manifest,
            identity=WatchdogIdentity(
                runtime_id=args.runtime_id,
                watchdog_id=args.watchdog_id,
            ),
            outbox=outbox,
            telemetry_client=client,
            build_driver=StubDriver,
        )

    class _ImmediateEvent:
        """A fake threading.Event whose wait() returns True immediately —
        simulates a signal handler having already fired before the first poll."""

        def wait(self, timeout=None):
            return True

    monkeypatch.setattr(entrypoint.threading, "Event", _ImmediateEvent)

    argv = [
        "--manifest",
        str(manifest_path),
        "--runtime-id",
        "rt-1",
        "--watchdog-id",
        "wd-1",
        "--ingest-url",
        "http://plane.internal",
    ]

    exit_code = entrypoint.main(
        argv,
        process_factory=_factory,
        process_tree_guard_factory=lambda: None,
        poll_interval_seconds=0.01,
    )

    assert exit_code == 0


def test_main_installs_process_tree_guard_before_constructing_process(tmp_path, monkeypatch):
    manifest = _manifest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest.to_dict()))
    events = []
    guard = object()

    def _install_guard():
        events.append(("guard", guard))
        return guard

    def _factory(args):
        events.append(("process", guard))
        process, _outbox = _process(
            tmp_path,
            transport=lambda envelope, headers: (202, {"event_id": 1}),
        )
        return process

    class _ImmediateEvent:
        def wait(self, timeout=None):
            return True

    monkeypatch.setattr(entrypoint.threading, "Event", _ImmediateEvent)

    exit_code = entrypoint.main(
        [
            "--manifest",
            str(manifest_path),
            "--runtime-id",
            "rt-1",
            "--watchdog-id",
            "wd-1",
            "--ingest-url",
            "http://plane.internal",
        ],
        process_factory=_factory,
        process_tree_guard_factory=_install_guard,
        poll_interval_seconds=0.01,
    )

    assert exit_code == 0
    assert events == [("guard", guard), ("process", guard)]


# ── Per-sink report wire contract across the process boundary (packet 20) ────


def test_to_envelope_carries_per_sink_state_on_a_separate_payload_key(tmp_path):
    process, _outbox = _process(tmp_path, transport=lambda envelope, headers: (202, {}))
    report = _report_with_sinks(
        process.driver.manifest,
        sinks=(
            _sink_report(sink_id="dev-a:csv", health=SinkHealth.HEALTHY),
            _sink_report(
                sink_id="dev-a:influx",
                sink_class="influx",
                health=SinkHealth.DEGRADED,
                delivery=SinkDeliveryState.DELIVERING,
                buffered_samples=32,
                sample_loss=2,
                failure_kind="sink_write",
                message="destination slow",
            ),
        ),
    )

    envelope = process.to_envelope(report)

    payload = envelope.payload
    # Source health and per-sink health cross the boundary on DISTINCT keys.
    assert [d["device_id"] for d in payload["devices"]] == ["dev-a"]
    assert {s["sink_id"]: s["health"] for s in payload["sinks"]} == {
        "dev-a:csv": "healthy",
        "dev-a:influx": "degraded",
    }
    influx = next(s for s in payload["sinks"] if s["sink_id"] == "dev-a:influx")
    assert influx["buffered_samples"] == 32
    assert influx["sample_loss"] == 2
    assert influx["failure_kind"] == "sink_write"


def test_to_envelope_omits_sinks_key_when_report_has_no_sinks(tmp_path):
    process, _outbox = _process(tmp_path, transport=lambda envelope, headers: (202, {}))

    envelope = process.to_envelope(_report(process.driver.manifest, sequence=0))

    assert "sinks" not in envelope.payload
    assert "devices" in envelope.payload


def test_sinks_survive_the_outbox_and_reach_delivery(tmp_path):
    delivered = []

    def _transport(envelope, headers):
        delivered.append(envelope)
        return 202, {"event_id": 1}

    process, _outbox = _process(tmp_path, transport=_transport)
    report = _report_with_sinks(
        process.driver.manifest,
        sinks=(_sink_report(health=SinkHealth.FAILED, delivery=SinkDeliveryState.FAILED),),
    )

    process.driver.emit(report)

    assert len(delivered) == 1
    assert delivered[0]["payload"]["sinks"][0]["health"] == "failed"


# ── Contract tests: TelemetryClient against the real ingest endpoint ─────────


def test_telemetry_client_classifies_a_real_202_as_delivered(app, client):
    _session_with_active_watchdog(
        app,
        dataflow_id="df-tc-202",
        runtime_id="rt-tc-202",
        watchdog_id="wd-tc-202",
        manifest_hash="hash-202",
    )
    telemetry_client = TelemetryClient(
        base_url="http://plane.internal", transport=_client_transport(client)
    )
    from app.contracts.watchdog_process_protocol import WatchdogTelemetryEnvelope

    envelope = WatchdogTelemetryEnvelope(
        report_id="wd-tc-202:0",
        dataflow_id="df-tc-202",
        runtime_id="rt-tc-202",
        watchdog_id="wd-tc-202",
        manifest_hash="hash-202",
        event_type="runtime.report",
        payload={"devices": []},
    )

    result = telemetry_client.send(envelope)

    assert result.outcome is DeliveryOutcome.DELIVERED
    assert result.status_code == 202


def test_telemetry_client_classifies_a_real_409_as_stale(app, client):
    """A watchdog_id that is not the active one is fenced with 409 (StaleWatchdogReport)."""
    _session_with_active_watchdog(
        app,
        dataflow_id="df-tc-409",
        runtime_id="rt-tc-409",
        watchdog_id="wd-active",
        manifest_hash="hash-409",
    )
    telemetry_client = TelemetryClient(
        base_url="http://plane.internal", transport=_client_transport(client)
    )
    from app.contracts.watchdog_process_protocol import WatchdogTelemetryEnvelope

    stale_envelope = WatchdogTelemetryEnvelope(
        report_id="wd-dead:0",
        dataflow_id="df-tc-409",
        runtime_id="rt-tc-409",
        watchdog_id="wd-dead",  # not the active watchdog_id
        manifest_hash="hash-409",
        event_type="runtime.report",
        payload={"devices": []},
    )

    result = telemetry_client.send(stale_envelope)

    assert result.outcome is DeliveryOutcome.STALE
    assert result.status_code == 409
    assert result.is_fatal is True


def test_telemetry_client_classifies_a_real_401_as_unauthorized(app):
    app.config["INGEST_TOKEN"] = "expected-token"
    flask_client = app.test_client()
    _session_with_active_watchdog(
        app,
        dataflow_id="df-tc-401",
        runtime_id="rt-tc-401",
        watchdog_id="wd-tc-401",
        manifest_hash="hash-401",
    )
    telemetry_client = TelemetryClient(
        base_url="http://plane.internal",
        token="wrong-token",
        transport=_client_transport(flask_client),
    )
    from app.contracts.watchdog_process_protocol import WatchdogTelemetryEnvelope

    envelope = WatchdogTelemetryEnvelope(
        report_id="wd-tc-401:0",
        dataflow_id="df-tc-401",
        runtime_id="rt-tc-401",
        watchdog_id="wd-tc-401",
        manifest_hash="hash-401",
        event_type="runtime.report",
        payload={"devices": []},
    )

    result = telemetry_client.send(envelope)

    assert result.outcome is DeliveryOutcome.UNAUTHORIZED
    assert result.status_code == 401
    assert result.is_fatal is True


def test_telemetry_client_classifies_a_real_400_as_rejected(app, client):
    """A manifest_hash mismatch against an otherwise-active watchdog_id is a
    ValueError -> 400, distinct from the fencing 409."""
    _session_with_active_watchdog(
        app,
        dataflow_id="df-tc-400",
        runtime_id="rt-tc-400",
        watchdog_id="wd-tc-400",
        manifest_hash="hash-400-correct",
    )
    telemetry_client = TelemetryClient(
        base_url="http://plane.internal", transport=_client_transport(client)
    )
    from app.contracts.watchdog_process_protocol import WatchdogTelemetryEnvelope

    mismatched_envelope = WatchdogTelemetryEnvelope(
        report_id="wd-tc-400:0",
        dataflow_id="df-tc-400",
        runtime_id="rt-tc-400",
        watchdog_id="wd-tc-400",
        manifest_hash="hash-400-wrong",
        event_type="runtime.report",
        payload={"devices": []},
    )

    result = telemetry_client.send(mismatched_envelope)

    assert result.outcome is DeliveryOutcome.REJECTED
    assert result.status_code == 400
    assert result.is_fatal is False
