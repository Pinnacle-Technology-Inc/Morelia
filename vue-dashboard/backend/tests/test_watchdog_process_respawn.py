"""Unit 8 — respawn claim policy.

Two halves, tested at their natural seams:

- Crash detection + respawn is entirely local to runtime_host's own process
  (``WatchdogProcessDriver.poll_health``, invoked from the ``/status`` GET
  handler's natural polling cadence — see ``app.runtime_host.server``). No
  DB, no daemon: covered with injected ``popen``/``pid_alive`` seams, exactly
  like ``TestWatchdogProcessDriver`` in ``test_runtime_host_supervision.py``.
- Atomic identity rotation into the durable ownership row, and respawn-budget
  escalation to ``UNCERTAIN``, is the daemon-side half
  (``HostSupervisor._reconcile_watchdog_status``) — covered against a real
  DB row, independent of any network transport.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import URL

from app import create_app
from app.control.supervisor import HostSupervisor
from app.database import db
from app.domain.enums import PolicyMode, RuntimeOwnershipState, SinkType, WatchdogProcessState
from app.models.session import Session
from app.runtime_child.driver import RuntimePhase
from app.runtime_host.manifest import MANIFEST_SCHEMA_VERSION, DeviceFlow, Manifest
from app.runtime_host.watchdog_process_driver import WatchdogProcessDriver

# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_runtime_host_supervision.py's driver fixtures)
# ---------------------------------------------------------------------------


class _FakeWatchdogProc:
    """Stand-in for the ``Popen`` handle of a spawned watchdog process child.

    ``exit_code`` (None while "alive") is mutated by the test to simulate a
    crash landing between two ``poll_health()`` calls.
    """

    def __init__(self, *, pid: int, ready: bool = True) -> None:
        self.pid = pid
        self.terminated = False
        self.killed = False
        self.stdout = iter(["READY\n"] if ready else [])
        self.exit_code: int | None = None

    def poll(self) -> int | None:
        return self.exit_code

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        self.killed = True


def _sequential_popen(procs: list[_FakeWatchdogProc]):
    """Return one fake proc per call, in order — models successive respawns."""
    calls: list[tuple[list[str], dict]] = []
    remaining = list(procs)

    def _popen(args, **kwargs):
        calls.append((list(args), kwargs))
        return remaining.pop(0)

    _popen.calls = calls
    return _popen


def _wpd_manifest(dataflow_id: str = "df-respawn-1") -> Manifest:
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        dataflow_id=dataflow_id,
        policy=PolicyMode.RECOMMEND,
        device_flows=(
            DeviceFlow(
                device_id="dev-a",
                name="device-a",
                nickname=None,
                hardware_id="hw-a",
                port="usb-1",
                parameters={},
                sink_type=SinkType.CSV,
                sink_location="/data/dev-a.csv",
            ),
        ),
    )


def _build_driver(
    tmp_path,
    *,
    runtime_id: str,
    popen,
    respawn_max_attempts: int,
    pid_alive=None,
) -> WatchdogProcessDriver:
    manifest = _wpd_manifest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest.to_dict()))
    kwargs = dict(
        manifest=manifest,
        manifest_path=str(manifest_path),
        on_report=lambda _: None,
        runtime_id=runtime_id,
        ingest_url="http://127.0.0.1:9",
        popen=popen,
        respawn_max_attempts=respawn_max_attempts,
    )
    if pid_alive is not None:
        kwargs["pid_alive"] = pid_alive
    return WatchdogProcessDriver(**kwargs)


# ---------------------------------------------------------------------------
# WatchdogProcessDriver — crash detection + respawn (acceptance #1)
# ---------------------------------------------------------------------------


class TestCrashDetectionAndRespawn:
    def test_poll_health_noop_while_process_alive(self, tmp_path):
        proc = _FakeWatchdogProc(pid=100)
        driver = _build_driver(
            tmp_path, runtime_id="rt-alive", popen=_sequential_popen([proc]),
            respawn_max_attempts=3,
        )
        driver.preflight()
        driver.start()
        first_id = driver.watchdog_id

        driver.poll_health()

        assert driver.watchdog_id == first_id
        assert driver.respawn_count == 0
        assert driver.watchdog_state is WatchdogProcessState.RUNNING

    def test_poll_health_noop_when_not_running(self, tmp_path):
        proc = _FakeWatchdogProc(pid=100)
        driver = _build_driver(
            tmp_path, runtime_id="rt-idle", popen=_sequential_popen([proc]),
            respawn_max_attempts=3,
        )
        # IDLE — never preflighted, nothing to supervise.
        driver.poll_health()
        assert driver.watchdog_id is None
        assert driver.respawn_count == 0

    def test_crash_triggers_respawn_with_new_identity_same_runtime_id(self, tmp_path):
        proc1 = _FakeWatchdogProc(pid=100)
        proc2 = _FakeWatchdogProc(pid=200)
        driver = _build_driver(
            tmp_path,
            runtime_id="rt-respawn-1",
            popen=_sequential_popen([proc1, proc2]),
            respawn_max_attempts=3,
        )
        driver.preflight()
        driver.start()
        original_watchdog_id = driver.watchdog_id
        original_token_hash = driver.watchdog_token_hash
        assert driver.watchdog_pid == 100

        proc1.exit_code = 1  # simulate the crash
        driver.poll_health()

        assert driver.phase is RuntimePhase.RUNNING, "runtime_id/supervision itself survives"
        assert driver.watchdog_id is not None
        assert driver.watchdog_id != original_watchdog_id, "new watchdog_id, not a reused one"
        assert driver.watchdog_token_hash != original_token_hash, "new token, too"
        assert driver.watchdog_pid == 200
        assert driver.watchdog_state is WatchdogProcessState.RUNNING
        assert driver.respawn_count == 1
        assert driver.respawn_exhausted is False
        assert driver.watchdog_exit_details == {
            "exit_code": 1,
            "watchdog_id": original_watchdog_id,
        }

        # A second poll while the replacement is healthy must not respawn again.
        driver.poll_health()
        assert driver.respawn_count == 1

    def test_adopted_process_crash_detected_via_pid_alive(self, tmp_path):
        alive = {"value": True}
        manifest = _wpd_manifest()
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest.to_dict()))

        class _ControlClient:
            def __init__(self, **_kwargs):
                pass

            def probe(self):
                return {
                    "watchdog_id": "wd-orphan",
                    "dataflow_id": manifest.dataflow_id,
                    "manifest_hash": manifest.hash,
                    "pid": 777,
                }

            def adopt(self, **_kwargs):
                return {"status": "adopted"}

        driver_adopted = WatchdogProcessDriver(
            manifest=manifest,
            manifest_path=str(manifest_path),
            on_report=lambda _: None,
            runtime_id="rt-adopted-crash",
            ingest_url="http://127.0.0.1:9",
            control_token="control-token",
            adopt_watchdog_id="wd-orphan",
            adopt_watchdog_pid=777,
            adopt_watchdog_control_port=43210,
            popen=_sequential_popen([_FakeWatchdogProc(pid=1000)]),
            respawn_max_attempts=1,
            pid_alive=lambda pid: alive["value"],
            control_client_factory=_ControlClient,
        )
        assert driver_adopted.adopted is True
        assert driver_adopted.watchdog_id == "wd-orphan"

        alive["value"] = False  # the adopted process is now gone
        driver_adopted.poll_health()

        assert driver_adopted.watchdog_id is not None
        assert driver_adopted.watchdog_id != "wd-orphan"
        assert driver_adopted.watchdog_pid == 1000
        assert driver_adopted.adopted is False, "the replacement was spawned by us, not adopted"
        assert driver_adopted.watchdog_exit_details == {
            "exit_code": None,  # unknowable for a process we never spawned
            "watchdog_id": "wd-orphan",
        }


# ---------------------------------------------------------------------------
# WatchdogProcessDriver — respawn budget exhaustion (acceptance #3)
# ---------------------------------------------------------------------------


class TestFailedSpawnAttemptRetries:
    def test_failed_spawn_attempt_is_retried_on_next_poll_tick(self, tmp_path):
        """A replacement that dies before READY must not end supervision while
        budget remains — the next poll tick retries (regression: poll_health
        used to return early forever once watchdog_id was None)."""
        procs = [
            _FakeWatchdogProc(pid=100),               # original
            _FakeWatchdogProc(pid=101, ready=False),  # respawn #1 dies in preflight
            _FakeWatchdogProc(pid=102),               # respawn #2 succeeds
        ]
        driver = _build_driver(
            tmp_path, runtime_id="rt-retry", popen=_sequential_popen(procs),
            respawn_max_attempts=3,
        )
        driver.preflight()
        driver.start()

        procs[0].exit_code = 1
        driver.poll_health()  # attempt #1 fails before READY
        assert driver.respawn_count == 1
        assert driver.watchdog_id is None
        assert driver.watchdog_state is WatchdogProcessState.CRASHED
        assert driver.respawn_exhausted is False

        driver.poll_health()  # attempt #2 retries and succeeds
        assert driver.respawn_count == 2
        assert driver.watchdog_id is not None
        assert driver.watchdog_pid == 102
        assert driver.watchdog_state is WatchdogProcessState.RUNNING

    def test_poll_health_is_noop_while_a_respawn_is_in_progress(self, tmp_path):
        """The poller probes every second but one Morelia spawn blocks ~10s+;
        a concurrent poll tick must not start a second competing spawn."""
        procs = [_FakeWatchdogProc(pid=100), _FakeWatchdogProc(pid=200)]
        driver = _build_driver(
            tmp_path, runtime_id="rt-lock", popen=_sequential_popen(procs),
            respawn_max_attempts=3,
        )
        driver.preflight()
        driver.start()
        procs[0].exit_code = 1

        with driver._respawn_lock:  # another /status thread is mid-respawn
            driver.poll_health()
        assert driver.respawn_count == 0, "tick during a respawn must be skipped"

        driver.poll_health()  # lock free again — crash handled normally
        assert driver.respawn_count == 1
        assert driver.watchdog_pid == 200

    def test_failed_spawn_attempts_still_exhaust_budget(self, tmp_path):
        procs = [
            _FakeWatchdogProc(pid=100),
            _FakeWatchdogProc(pid=101, ready=False),
            _FakeWatchdogProc(pid=102, ready=False),
        ]
        driver = _build_driver(
            tmp_path, runtime_id="rt-retry-exhaust", popen=_sequential_popen(procs),
            respawn_max_attempts=2,
        )
        driver.preflight()
        driver.start()

        procs[0].exit_code = 1
        driver.poll_health()  # attempt #1 fails
        driver.poll_health()  # attempt #2 fails
        assert driver.respawn_count == 2
        assert driver.respawn_exhausted is False

        driver.poll_health()  # no budget left — trap shuts
        assert driver.respawn_exhausted is True
        assert driver.respawn_count == 2
        assert driver.watchdog_id is None

        driver.poll_health()  # and stays shut
        assert driver.respawn_exhausted is True


class TestRespawnBudgetExhaustion:
    def test_repeated_crashes_exhaust_budget_and_stop_respawning(self, tmp_path):
        procs = [_FakeWatchdogProc(pid=100 + i) for i in range(3)]
        driver = _build_driver(
            tmp_path,
            runtime_id="rt-exhaust",
            popen=_sequential_popen(procs),
            respawn_max_attempts=2,
        )
        driver.preflight()
        driver.start()  # consumes procs[0]

        procs[0].exit_code = 1
        driver.poll_health()  # respawn #1 -> procs[1]
        assert driver.respawn_count == 1
        assert driver.respawn_exhausted is False
        assert driver.watchdog_pid == 101

        procs[1].exit_code = 1
        driver.poll_health()  # respawn #2 -> procs[2]
        assert driver.respawn_count == 2
        assert driver.respawn_exhausted is False
        assert driver.watchdog_pid == 102

        procs[2].exit_code = 1
        driver.poll_health()  # budget exhausted: no procs[3] to pop

        assert driver.respawn_exhausted is True
        # The exhausting crash itself doesn't consume another attempt.
        assert driver.respawn_count == 2
        assert driver.watchdog_id is None
        assert driver.watchdog_pid is None
        assert driver.watchdog_state is WatchdogProcessState.CRASHED
        assert driver.watchdog_exit_details["exit_code"] == 1

        # Budget stays exhausted — no infinite crash/respawn loop.
        driver.poll_health()
        assert driver.respawn_exhausted is True
        assert driver.respawn_count == 2

    def test_zero_budget_never_respawns(self, tmp_path):
        proc = _FakeWatchdogProc(pid=100)
        driver = _build_driver(
            tmp_path, runtime_id="rt-zero-budget", popen=_sequential_popen([proc]),
            respawn_max_attempts=0,
        )
        driver.preflight()
        driver.start()

        proc.exit_code = 1
        driver.poll_health()

        assert driver.respawn_exhausted is True
        assert driver.respawn_count == 0
        assert driver.watchdog_id is None
        assert driver.watchdog_state is WatchdogProcessState.CRASHED


class TestRespawnMaxAttemptsConfigDefault:
    def test_defaults_from_config_when_not_passed(self, tmp_path):
        # Config attributes are frozen at class-definition time (module
        # import), so this asserts against the live config value rather than
        # monkeypatching the environment variable (which would have no
        # effect after import) — see app/config.py's Config class body.
        from app.config import get_config

        expected = get_config().WATCHDOG_RESPAWN_MAX_ATTEMPTS

        manifest = _wpd_manifest()
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest.to_dict()))
        driver = WatchdogProcessDriver(
            manifest=manifest,
            manifest_path=str(manifest_path),
            on_report=lambda _: None,
            runtime_id="rt-config-default",
            ingest_url="http://127.0.0.1:9",
            popen=_sequential_popen([_FakeWatchdogProc(pid=1)]),
        )
        assert driver._respawn_max_attempts == expected


# ---------------------------------------------------------------------------
# HostSupervisor — atomic identity rotation + uncertain escalation
# (acceptance #2, #3)
# ---------------------------------------------------------------------------


@pytest.fixture()
def respawn_app(tmp_path):
    url = URL.create("sqlite", database=str(tmp_path / "respawn.sqlite3"))
    app = create_app("testing", config_overrides={"SQLALCHEMY_DATABASE_URI": url})
    with app.app_context():
        db.create_all()
    return app


@pytest.fixture()
def respawn_session_id(respawn_app):
    with respawn_app.app_context():
        row = Session(
            name="respawn-test",
            dataflow_id="df-respawn-reconcile",
            policy=PolicyMode.RECOMMEND,
            device_flows=[],
        )
        db.session.add(row)
        db.session.commit()
        return row.id


class TestHostSupervisorWatchdogReconciliation:
    def test_reconcile_watchdog_status_claims_new_identity_on_respawn(
        self, respawn_app, respawn_session_id
    ):
        with respawn_app.app_context():
            sup = HostSupervisor()
            sup._ownerships.create_starting(
                runtime_id="rt-recon-1",
                session_id=respawn_session_id,
                dataflow_id="df-respawn-reconcile",
                manifest_hash="hash-1",
                token="tok",
            )
            sup._ownerships.set_watchdog(
                "rt-recon-1", watchdog_id="wd-old", token_hash="hash-old", pid=111,
            )

            sup._reconcile_watchdog_status(
                {
                    "runtime_id": "rt-recon-1",
                    "watchdog_id": "wd-new",
                    "watchdog_pid": 222,
                    "watchdog_token_hash": "hash-new",
                    "watchdog_state": "running",
                    "watchdog_respawn_exhausted": False,
                    "watchdog_exit_details": None,
                }
            )

            row = sup._ownerships.get("rt-recon-1")
            assert row.watchdog_id == "wd-new"
            assert row.watchdog_pid == 222
            assert row.watchdog_token_hash == "hash-new"
            # A fresh identity claim starts as STARTING regardless of the
            # reported state — the very next reconcile cycle syncs it to
            # RUNNING once the report shows the same (now-active) id.
            assert row.watchdog_state is WatchdogProcessState.STARTING
            assert row.watchdog_exit_details is None

    def test_reconcile_watchdog_status_syncs_state_without_identity_change(
        self, respawn_app, respawn_session_id
    ):
        with respawn_app.app_context():
            sup = HostSupervisor()
            sup._ownerships.create_starting(
                runtime_id="rt-recon-2",
                session_id=respawn_session_id,
                dataflow_id="df-respawn-reconcile",
                manifest_hash="hash-1",
                token="tok",
            )
            sup._ownerships.set_watchdog(
                "rt-recon-2", watchdog_id="wd-same", token_hash="hash", pid=111,
            )

            sup._reconcile_watchdog_status(
                {
                    "runtime_id": "rt-recon-2",
                    "watchdog_id": "wd-same",
                    "watchdog_pid": 111,
                    "watchdog_state": "running",
                    "watchdog_respawn_exhausted": False,
                    "watchdog_exit_details": None,
                }
            )

            row = sup._ownerships.get("rt-recon-2")
            assert row.watchdog_id == "wd-same"
            assert row.watchdog_state is WatchdogProcessState.RUNNING
            assert row.watchdog_last_seen_at is not None

    def test_reconcile_watchdog_status_escalates_to_uncertain_on_budget_exhaustion(
        self, respawn_app, respawn_session_id
    ):
        with respawn_app.app_context():
            sup = HostSupervisor()
            sup._ownerships.create_starting(
                runtime_id="rt-recon-3",
                session_id=respawn_session_id,
                dataflow_id="df-respawn-reconcile",
                manifest_hash="hash-1",
                token="tok",
            )
            sup._ownerships.set_watchdog(
                "rt-recon-3", watchdog_id="wd-doomed", token_hash="hash", pid=111,
            )

            sup._reconcile_watchdog_status(
                {
                    "runtime_id": "rt-recon-3",
                    "watchdog_id": None,
                    "watchdog_pid": None,
                    "watchdog_state": "crashed",
                    "watchdog_respawn_count": 3,
                    "watchdog_respawn_exhausted": True,
                    "watchdog_exit_details": {"exit_code": 1, "watchdog_id": "wd-doomed"},
                }
            )

            row = sup._ownerships.get("rt-recon-3")
            assert row.watchdog_state is WatchdogProcessState.CRASHED
            assert row.watchdog_exit_details == {"exit_code": 1, "watchdog_id": "wd-doomed"}
            assert row.state is RuntimeOwnershipState.UNCERTAIN
            assert row.details["reason"] == "watchdog_respawn_exhausted"

    def test_reconcile_watchdog_status_crash_without_exhaustion_stays_active(
        self, respawn_app, respawn_session_id
    ):
        """A crash mid-respawn-budget must not itself escalate the runtime row."""
        with respawn_app.app_context():
            sup = HostSupervisor()
            sup._ownerships.create_starting(
                runtime_id="rt-recon-4",
                session_id=respawn_session_id,
                dataflow_id="df-respawn-reconcile",
                manifest_hash="hash-1",
                token="tok",
            )
            sup._ownerships.set_watchdog(
                "rt-recon-4", watchdog_id="wd-transient", token_hash="hash", pid=111,
            )
            sup._ownerships.mark_running(  # simulate an already-RUNNING runtime row
                "rt-recon-4", pid=999, port=12345,
            )

            # The driver already spawned a replacement by the time /status is
            # probed (poll_health runs synchronously in the GET handler), so
            # the new identity is reported directly — not an interim "None".
            sup._reconcile_watchdog_status(
                {
                    "runtime_id": "rt-recon-4",
                    "watchdog_id": "wd-replacement",
                    "watchdog_pid": 222,
                    "watchdog_state": "running",
                    "watchdog_respawn_exhausted": False,
                    "watchdog_exit_details": {
                        "exit_code": 1,
                        "watchdog_id": "wd-transient",
                    },
                }
            )

            row = sup._ownerships.get("rt-recon-4")
            assert row.watchdog_id == "wd-replacement"
            assert row.state is RuntimeOwnershipState.RUNNING, "no false escalation"

    def test_reconcile_watchdog_status_noop_for_unknown_runtime_id(
        self, respawn_app
    ):
        with respawn_app.app_context():
            sup = HostSupervisor()
            # Must not raise for a runtime_id with no ownership row at all.
            sup._reconcile_watchdog_status(
                {"runtime_id": "rt-unknown", "watchdog_id": "wd-x", "watchdog_state": "running"}
            )
            assert sup._ownerships.get("rt-unknown") is None
