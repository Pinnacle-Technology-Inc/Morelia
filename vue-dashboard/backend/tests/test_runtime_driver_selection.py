from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import URL

from app import create_app
from app.control.supervisor import HostSupervisor
from app.database import db
from app.domain.enums import PolicyMode, SinkType
from app.models.runtime_ownership import RuntimeOwnership
from app.models.session import Session
from app.runtime_child.morelia import preflight_sink_dependencies
from app.runtime_host.manifest import (
    MANIFEST_SCHEMA_VERSION,
    DeviceFlow,
    Manifest,
    SinkConfig,
)


class FakePopen:
    calls: list[list[str]] = []

    def __init__(self, args, **kwargs) -> None:
        self.args = list(args)
        self.kwargs = kwargs
        self.stdout = iter(["PORT:54321\n", "READY\n"])
        self.pid = 12345
        self._terminated = False
        FakePopen.calls.append(self.args)

    def terminate(self) -> None:
        self._terminated = True

    def wait(self, timeout=None):  # noqa: ANN001 - matches subprocess API
        return 0

    def poll(self):
        return 0 if self._terminated else None


def _session() -> Session:
    return Session(
        name="driver-selection",
        dataflow_id="df-driver-selection",
        policy=PolicyMode.RECOMMEND,
        device_flows=[
            {
                "device_id": "dev-driver-selection",
                "name": "device-driver-selection",
                "nickname": None,
                "hardware_id": "hw-driver-selection",
                "port": "COM4",
                "parameters": {},
                "sink_type": "csv",
                "sink_location": "driver-selection.csv",
            }
        ],
    )


def test_supervisor_passes_configured_runtime_driver_to_spawned_host(
    monkeypatch,
    tmp_path,
):
    import app.control.supervisor as supervisor

    FakePopen.calls.clear()
    monkeypatch.setattr(supervisor.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(
        supervisor, "ensure_runtime_driver_ready", lambda driver, manifest=None: None
    )

    database_url = URL.create("sqlite", database=str(tmp_path / "driver.sqlite3"))
    app = create_app(
        "testing",
        config_overrides={
            "SQLALCHEMY_DATABASE_URI": database_url,
            "RUNTIME_DRIVER": "morelia",
        },
    )
    with app.app_context():
        db.create_all()
        session = _session()
        db.session.add(session)
        db.session.commit()

        supervisor_instance = HostSupervisor()
        supervisor_instance.spawn(session)
        entry = supervisor_instance._children["df-driver-selection"]

        try:
            args = FakePopen.calls[0]
            assert args[0:3] == [supervisor.sys.executable, "-m", "app.runtime_host"]
            assert args[args.index("--driver") + 1] == "morelia"
        finally:
            Path(entry.manifest_path).unlink(missing_ok=True)


def test_supervisor_checks_driver_before_creating_runtime_ownership(
    monkeypatch,
    tmp_path,
):
    import app.control.supervisor as supervisor

    def fail_preflight(driver: str, manifest=None) -> None:
        raise RuntimeError(f"{driver} driver unavailable")

    monkeypatch.setattr(supervisor, "ensure_runtime_driver_ready", fail_preflight)

    database_url = URL.create("sqlite", database=str(tmp_path / "driver-fail.sqlite3"))
    app = create_app(
        "testing",
        config_overrides={
            "SQLALCHEMY_DATABASE_URI": database_url,
            "RUNTIME_DRIVER": "morelia",
        },
    )
    with app.app_context():
        db.create_all()
        session = _session()
        db.session.add(session)
        db.session.commit()

        supervisor_instance = HostSupervisor()
        with pytest.raises(RuntimeError) as exc_info:
            supervisor_instance.spawn(session)

        assert str(exc_info.value) == "morelia driver unavailable"
        assert db.session.scalars(db.select(RuntimeOwnership)).all() == []


# ── Selection-aware sink dependency preflight (gap SINK-13) ──────────────────


def _sink(sink_type: SinkType, *, sink_id: str, name: str, **parameters) -> SinkConfig:
    return SinkConfig(sink_id=sink_id, name=name, type=sink_type, parameters=dict(parameters))


def _manifest_with_sinks(*sinks: SinkConfig, dataflow_id: str = "df-preflight") -> Manifest:
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        dataflow_id=dataflow_id,
        policy=PolicyMode.RECOMMEND,
        device_flows=(
            DeviceFlow(
                device_id="dev-preflight",
                name="device-preflight",
                nickname=None,
                hardware_id="hw-preflight",
                port="COM7",
                parameters={},
                sinks=sinks,
            ),
        ),
    )


def test_preflight_passes_for_csv_only_even_when_all_optional_imports_missing(monkeypatch):
    """A CSV-only session must always pass: CSV has no external dependency, so a
    missing optional/native import for an UNSELECTED type can never block it."""
    import app.runtime_child.sink_factory as sink_factory

    # Force every optional/native import to look unavailable.
    monkeypatch.setattr(sink_factory, "_probe_import", lambda name: False)

    manifest = _manifest_with_sinks(
        _sink(SinkType.CSV, sink_id="dev-preflight:csv", name="csv", file_path="run.csv")
    )

    # Does not raise — the unselected edf/influx/quest/pvfs deps are never probed.
    preflight_sink_dependencies(manifest)


def test_preflight_fails_sink_addressed_when_selected_sink_dependency_missing(monkeypatch):
    import app.runtime_child.sink_factory as sink_factory
    from app.runtime_child.sink_factory import SinkDependencyMissing

    monkeypatch.setattr(sink_factory, "_probe_import", lambda name: False)

    manifest = _manifest_with_sinks(
        _sink(SinkType.CSV, sink_id="dev-preflight:csv", name="csv", file_path="run.csv"),
        _sink(SinkType.QUEST, sink_id="dev-preflight:quest", name="quest"),
    )

    with pytest.raises(SinkDependencyMissing) as exc_info:
        preflight_sink_dependencies(manifest)

    # Sink-addressed + redacted: names the exact sink and the pip extra, no secrets.
    assert exc_info.value.sink_id == "dev-preflight:quest"
    assert exc_info.value.sink_type is SinkType.QUEST
    assert exc_info.value.extra == "quest"


def test_spawn_fails_before_ownership_when_selected_sink_dependency_missing(
    monkeypatch, tmp_path
):
    """A missing selected-sink dependency fails the start before any runtime
    ownership row is created or any child is spawned (session stays restartable)."""
    import app.control.supervisor as supervisor
    import app.runtime_child.morelia as morelia
    import app.runtime_child.sink_factory as sink_factory

    # Base morelia import is not the thing under test here — make it succeed so
    # the selection-aware sink dependency check is what fails.
    monkeypatch.setattr(morelia, "_import_morelia", lambda: None)
    monkeypatch.setattr(sink_factory, "_probe_import", lambda name: False)

    def _explode_if_spawned(*args, **kwargs):
        raise AssertionError("child process must not be spawned when preflight fails")

    monkeypatch.setattr(supervisor.subprocess, "Popen", _explode_if_spawned)

    database_url = URL.create("sqlite", database=str(tmp_path / "sink-dep.sqlite3"))
    app = create_app(
        "testing",
        config_overrides={
            "SQLALCHEMY_DATABASE_URI": database_url,
            "RUNTIME_DRIVER": "morelia",
        },
    )
    with app.app_context():
        db.create_all()
        session = _session()
        db.session.add(session)
        db.session.commit()

        manifest = _manifest_with_sinks(
            _sink(SinkType.QUEST, sink_id="dev-preflight:quest", name="quest"),
            dataflow_id=session.dataflow_id,
        )

        supervisor_instance = HostSupervisor()
        with pytest.raises(sink_factory.SinkDependencyMissing) as exc_info:
            supervisor_instance.spawn(session, manifest=manifest)

        assert exc_info.value.sink_id == "dev-preflight:quest"
        assert db.session.scalars(db.select(RuntimeOwnership)).all() == []
        assert "df-driver-selection" not in supervisor_instance._children
