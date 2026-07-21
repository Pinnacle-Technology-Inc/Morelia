import pytest

from app import create_app
from app.database import db
from app.domain.enums import RuntimeOwnershipState, WatchdogProcessState
from app.domain.errors import StaleWatchdogReport
from app.models.session import Session
from app.repositories.runtime_ownership import RuntimeOwnershipRepository


def test_runtime_ownership_repository_records_lifecycle():
    app = create_app("testing")
    repo = RuntimeOwnershipRepository()
    with app.app_context():
        db.create_all()
        db.session.add(Session(id=1, name="runtime-owner", dataflow_id="df-owner"))
        db.session.commit()

        row = repo.create_starting(
            runtime_id="rt-1",
            session_id=1,
            dataflow_id="df-owner",
            manifest_hash="hash-1",
            token="token-1",
        )
        assert row.state is RuntimeOwnershipState.STARTING
        assert row.started_at is not None

        running = repo.mark_running("rt-1", pid=1234, port=8765)
        assert running.state is RuntimeOwnershipState.RUNNING
        assert running.pid == 1234
        assert running.port == 8765
        assert running.last_seen_at is not None

        adopted = repo.mark_adopted("rt-1", port=8765)
        assert adopted.state is RuntimeOwnershipState.ADOPTED
        assert adopted.adopted_at is not None

        stopped = repo.mark_stopped("rt-1")
        assert stopped.state is RuntimeOwnershipState.STOPPED
        assert stopped.stopped_at is not None


def test_active_for_dataflow_ignores_stopped_runtime():
    app = create_app("testing")
    repo = RuntimeOwnershipRepository()
    with app.app_context():
        db.create_all()
        db.session.add(Session(id=1, name="runtime-owner", dataflow_id="df-owner"))
        db.session.commit()

        repo.create_starting(
            runtime_id="rt-stopped",
            session_id=1,
            dataflow_id="df-owner",
            manifest_hash="hash-1",
            token="token-1",
        )
        repo.mark_stopped("rt-stopped")

        assert repo.active_for_dataflow("df-owner") is None


def test_recovering_runtime_stays_active_and_exposes_retry_details():
    app = create_app("testing")
    repo = RuntimeOwnershipRepository()
    with app.app_context():
        db.create_all()
        db.session.add(Session(id=1, name="runtime-owner", dataflow_id="df-owner"))
        db.session.commit()
        repo.create_starting(
            runtime_id="rt-recovering",
            session_id=1,
            dataflow_id="df-owner",
            manifest_hash="hash-1",
            token="token-1",
        )

        row = repo.mark_recovering(
            "rt-recovering",
            phase="retry_wait",
            reason="watchdog_identity_ambiguous",
            attempt=3,
            next_retry_at="2026-07-16T15:31:00Z",
            evidence={"pid_alive": True, "identity_verified": False},
        )

        assert row.state is RuntimeOwnershipState.RECOVERING
        assert row.details["recovery"]["hardware_access"] == "blocked"
        assert row.details["recovery"]["attempt"] == 3
        assert repo.active_for_dataflow("df-owner").runtime_id == "rt-recovering"


def test_watchdog_identity_defaults_unset_for_existing_callers():
    app = create_app("testing")
    repo = RuntimeOwnershipRepository()
    with app.app_context():
        db.create_all()
        db.session.add(Session(id=1, name="runtime-owner", dataflow_id="df-owner"))
        db.session.commit()

        row = repo.create_starting(
            runtime_id="rt-no-watchdog",
            session_id=1,
            dataflow_id="df-owner",
            manifest_hash="hash-1",
            token="token-1",
        )
        assert row.watchdog_id is None
        assert row.watchdog_state is None
        assert row.watchdog_pid is None
        assert row.watchdog_outbox_path is None
        assert row.watchdog_last_seen_at is None
        assert row.watchdog_exit_details is None

        # Existing lifecycle transitions remain unaffected by the new columns.
        running = repo.mark_running("rt-no-watchdog", pid=111, port=2222)
        assert running.state is RuntimeOwnershipState.RUNNING
        assert running.watchdog_id is None


def test_watchdog_identity_set_update_crash_respawn_stop_clear():
    app = create_app("testing")
    repo = RuntimeOwnershipRepository()
    with app.app_context():
        db.create_all()
        db.session.add(Session(id=1, name="runtime-owner", dataflow_id="df-owner"))
        db.session.commit()

        repo.create_starting(
            runtime_id="rt-wd",
            session_id=1,
            dataflow_id="df-owner",
            manifest_hash="hash-1",
            token="token-1",
        )

        started = repo.set_watchdog(
            "rt-wd",
            watchdog_id="wd-1",
            token_hash="hash-of-token-1",
            pid=4321,
            outbox_path="/outbox/wd-1.sqlite3",
        )
        assert started.watchdog_id == "wd-1"
        assert started.watchdog_token_hash == "hash-of-token-1"
        assert started.watchdog_pid == 4321
        assert started.watchdog_outbox_path == "/outbox/wd-1.sqlite3"
        assert started.watchdog_state is WatchdogProcessState.STARTING
        assert started.watchdog_last_seen_at is not None

        seen = repo.update_watchdog_seen("rt-wd", watchdog_id="wd-1", pid=4321)
        assert seen.watchdog_state is WatchdogProcessState.RUNNING
        assert seen.watchdog_pid == 4321

        crashed = repo.mark_watchdog_crashed(
            "rt-wd", watchdog_id="wd-1", details={"exit_code": 1}
        )
        assert crashed.watchdog_state is WatchdogProcessState.CRASHED
        assert crashed.watchdog_exit_details == {"exit_code": 1}
        # runtime_id identity itself is untouched by a watchdog-process crash.
        assert crashed.runtime_id == "rt-wd"

        # Respawn: a fresh watchdog_id replaces the crashed one and clears
        # the previous exit details.
        respawned = repo.set_watchdog(
            "rt-wd", watchdog_id="wd-2", token_hash="hash-of-token-2"
        )
        assert respawned.watchdog_id == "wd-2"
        assert respawned.watchdog_exit_details is None
        assert respawned.watchdog_state is WatchdogProcessState.STARTING

        stopped = repo.mark_watchdog_stopped(
            "rt-wd", watchdog_id="wd-2", details={"reason": "session stop"}
        )
        assert stopped.watchdog_state is WatchdogProcessState.STOPPED
        assert stopped.watchdog_exit_details == {"reason": "session stop"}

        cleared = repo.clear_watchdog("rt-wd")
        assert cleared.watchdog_id is None
        assert cleared.watchdog_token_hash is None
        assert cleared.watchdog_pid is None
        assert cleared.watchdog_outbox_path is None
        assert cleared.watchdog_state is None
        assert cleared.watchdog_last_seen_at is None
        assert cleared.watchdog_exit_details is None


def test_adopt_watchdog_claims_a_survived_watchdog_into_a_fresh_row():
    """Packet 06: a brand-new runtime_id row (fresh runtime_host) adopting a
    watchdog process an earlier, now-dead runtime_id's row left behind."""
    app = create_app("testing")
    repo = RuntimeOwnershipRepository()
    with app.app_context():
        db.create_all()
        db.session.add(Session(id=1, name="runtime-owner", dataflow_id="df-owner"))
        db.session.commit()

        repo.create_starting(
            runtime_id="rt-new",
            session_id=1,
            dataflow_id="df-owner",
            manifest_hash="hash-1",
            token="token-new",
        )

        adopted = repo.adopt_watchdog(
            "rt-new", watchdog_id="wd-orphan", pid=9999, control_port=43210
        )
        assert adopted.watchdog_id == "wd-orphan"
        assert adopted.watchdog_pid == 9999
        assert adopted.watchdog_control_port == 43210
        assert adopted.watchdog_state is WatchdogProcessState.ADOPTED
        assert adopted.watchdog_adopted_at is not None
        assert adopted.watchdog_last_seen_at is not None


def test_adopt_watchdog_rejects_a_row_that_already_has_one():
    app = create_app("testing")
    repo = RuntimeOwnershipRepository()
    with app.app_context():
        db.create_all()
        db.session.add(Session(id=1, name="runtime-owner", dataflow_id="df-owner"))
        db.session.commit()

        repo.create_starting(
            runtime_id="rt-new",
            session_id=1,
            dataflow_id="df-owner",
            manifest_hash="hash-1",
            token="token-new",
        )
        repo.set_watchdog("rt-new", watchdog_id="wd-1", token_hash="hash-1")

        with pytest.raises(ValueError, match="already has an active watchdog"):
            repo.adopt_watchdog("rt-new", watchdog_id="wd-orphan", pid=9999)


# ---------------------------------------------------------------------------
# Packet 07 — fencing: a report naming a stale watchdog_id must be rejected,
# not silently applied, and must not overwrite the active row's state.
# ---------------------------------------------------------------------------


def _rt_with_active_watchdog(repo: RuntimeOwnershipRepository, *, runtime_id: str) -> None:
    repo.create_starting(
        runtime_id=runtime_id,
        session_id=1,
        dataflow_id="df-owner",
        manifest_hash="hash-1",
        token="token-1",
    )
    repo.set_watchdog(runtime_id, watchdog_id="wd-active", token_hash="hash-of-active")


@pytest.mark.parametrize(
    "call",
    [
        lambda repo, rt: repo.update_watchdog_seen(rt, watchdog_id="wd-stale", pid=1),
        lambda repo, rt: repo.mark_watchdog_crashed(
            rt, watchdog_id="wd-stale", details={"exit_code": 1}
        ),
        lambda repo, rt: repo.mark_watchdog_stopped(
            rt, watchdog_id="wd-stale", details={"reason": "stale"}
        ),
        lambda repo, rt: repo.mark_watchdog_adopted(rt, watchdog_id="wd-stale"),
        lambda repo, rt: repo.mark_watchdog_uncertain(
            rt, watchdog_id="wd-stale", details={"source": "control_plane_staleness"}
        ),
    ],
    ids=[
        "update_watchdog_seen",
        "mark_watchdog_crashed",
        "mark_watchdog_stopped",
        "mark_watchdog_adopted",
        "mark_watchdog_uncertain",
    ],
)
def test_stale_watchdog_report_is_rejected_not_applied(call):
    """A report naming a watchdog_id that is not the row's active one must
    raise StaleWatchdogReport and must not mutate the row at all."""
    app = create_app("testing")
    repo = RuntimeOwnershipRepository()
    with app.app_context():
        db.create_all()
        db.session.add(Session(id=1, name="runtime-owner", dataflow_id="df-owner"))
        db.session.commit()
        _rt_with_active_watchdog(repo, runtime_id="rt-fenced")

        before = repo.get("rt-fenced")
        before_state = before.watchdog_state
        before_details = before.watchdog_exit_details

        with pytest.raises(StaleWatchdogReport) as exc_info:
            call(repo, "rt-fenced")
        assert exc_info.value.reported_watchdog_id == "wd-stale"
        assert exc_info.value.active_watchdog_id == "wd-active"

        after = repo.get("rt-fenced")
        assert after.watchdog_id == "wd-active"
        assert after.watchdog_state is before_state
        assert after.watchdog_exit_details == before_details


def test_stale_watchdog_report_rejected_when_no_watchdog_is_active():
    """A report naming an id is never valid against "no active watchdog"."""
    app = create_app("testing")
    repo = RuntimeOwnershipRepository()
    with app.app_context():
        db.create_all()
        db.session.add(Session(id=1, name="runtime-owner", dataflow_id="df-owner"))
        db.session.commit()

        repo.create_starting(
            runtime_id="rt-no-watchdog-yet",
            session_id=1,
            dataflow_id="df-owner",
            manifest_hash="hash-1",
            token="token-1",
        )

        with pytest.raises(StaleWatchdogReport) as exc_info:
            repo.update_watchdog_seen("rt-no-watchdog-yet", watchdog_id="wd-anything")
        assert exc_info.value.active_watchdog_id is None


def test_mark_watchdog_uncertain_requires_provenance_and_fences():
    app = create_app("testing")
    repo = RuntimeOwnershipRepository()
    with app.app_context():
        db.create_all()
        db.session.add(Session(id=1, name="runtime-owner", dataflow_id="df-owner"))
        db.session.commit()
        _rt_with_active_watchdog(repo, runtime_id="rt-uncertain")

        with pytest.raises(ValueError, match="provenance"):
            repo.mark_watchdog_uncertain("rt-uncertain", watchdog_id="wd-active", details={})

        uncertain = repo.mark_watchdog_uncertain(
            "rt-uncertain",
            watchdog_id="wd-active",
            details={"source": "control_plane_staleness"},
        )
        assert uncertain.watchdog_state is WatchdogProcessState.UNCERTAIN
        assert uncertain.watchdog_exit_details == {"source": "control_plane_staleness"}
        # runtime_id/watchdog_id identity itself is untouched by an uncertain verdict.
        assert uncertain.watchdog_id == "wd-active"
