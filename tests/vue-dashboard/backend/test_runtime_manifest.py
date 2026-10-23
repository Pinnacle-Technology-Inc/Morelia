"""Persistence round-trip tests for the RuntimeManifest model (Packets 3.4 & 3.5)."""

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.database import db
from app.domain.enums import PolicyMode, SinkType
from app.domain.errors import EmptySession, SessionNotFound, UnresolvableSession
from app.models.runtime_manifest import RuntimeManifest
from app.repositories.sessions import SessionRepository
from app.runtime_host.manifest import MANIFEST_SCHEMA_VERSION, DeviceFlow, Manifest
from app.services import device_templates, manifests, session_config


@pytest.fixture(autouse=True)
def enumerated_hardware(monkeypatch):
    monkeypatch.setattr("serial.tools.list_ports.comports", lambda: [
        SimpleNamespace(serial_number="002", device="/dev/ttyUSB0"),
        SimpleNamespace(serial_number="004", device="/dev/ttyUSB1"),
    ])


def _make_manifest() -> Manifest:
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        dataflow_id="df-persist",
        policy=PolicyMode.RECOMMEND,
        device_flows=(
            DeviceFlow(
                device_id="dev-1",
                name="device-1",
                nickname=None,
                hardware_id="001",
                port="usb-1",
                parameters={"sample_rate": 250},
                sink_type=SinkType.CSV,
                sink_location="/data/dev-1.csv",
            ),
        ),
    )


def _create_session(app) -> int:
    with app.app_context():
        return SessionRepository().create({"name": "Manifest Session"}).id


def test_runtime_manifest_persists_and_reconstructs_hash_equal(app):
    manifest = _make_manifest()
    session_id = _create_session(app)

    with app.app_context():
        row = RuntimeManifest(
            hash=manifest.hash,
            schema_version=manifest.schema_version,
            session_id=session_id,
            content=manifest.to_dict(),
        )
        db.session.add(row)
        db.session.commit()

        fetched = RuntimeManifest.query.filter_by(hash=manifest.hash).first()
        assert fetched is not None
        reconstructed = Manifest.from_dict(fetched.content)
        assert reconstructed.hash == fetched.hash
        assert reconstructed == manifest


def test_runtime_manifest_hash_column_is_unique(app):
    """The hash column has a unique constraint; inserting the same hash twice fails."""
    manifest = _make_manifest()
    session_id = _create_session(app)

    with app.app_context():
        row1 = RuntimeManifest(
            hash=manifest.hash,
            schema_version=manifest.schema_version,
            session_id=session_id,
            content=manifest.to_dict(),
        )
        db.session.add(row1)
        db.session.commit()

        row2 = RuntimeManifest(
            hash=manifest.hash,
            schema_version=manifest.schema_version,
            session_id=session_id,
            content=manifest.to_dict(),
        )
        db.session.add(row2)
        with pytest.raises(IntegrityError):
            db.session.commit()


# ---------------------------------------------------------------------------
# Resolver tests (Packet 3.5)
# ---------------------------------------------------------------------------

_DEVICE_CONTENT = {
    "type": "pod8206hr",
    "parameters": {"preamp_gain": 10, "sample_rate": 2000},
}

_DEVICE_FLOW_ENTRY = {
    "hardware_id": "002",
    "port": "/dev/ttyUSB0",
    "sink_type": "csv",
    "sink_location": "/data/out.csv",
}


def _build_session(app, template_path: str, *, nickname: str | None = None) -> int:
    """Create a session with one device_flow referencing *template_path*."""
    entry = {**_DEVICE_FLOW_ENTRY, "device_template_path": template_path}
    if nickname:
        entry["nickname"] = nickname
    with app.app_context():
        return session_config.import_config(
            {
                "name": "Resolver Test",
                "policy": "recommend",
                "device_flows": [entry],
            }
        ).id


def test_resolve_produces_manifest_with_snapshotted_params_and_persists_row(app):
    """resolve() returns a Manifest matching the referenced config and persists a row."""
    with app.app_context():
        template_path = device_templates.create("resolver-pod", _DEVICE_CONTENT).file_path

    session_id = _build_session(app, template_path)

    with app.app_context():
        manifest = manifests.resolve(session_id)

        assert manifest.policy == PolicyMode.RECOMMEND
        assert len(manifest.device_flows) == 1
        df = manifest.device_flows[0]
        assert df.parameters == {"preamp_gain": 10, "sample_rate": 2000}
        assert df.sink_type == SinkType.CSV
        assert df.sink_location == "/data/out.csv"

        row = db.session.scalars(
            db.select(RuntimeManifest).where(RuntimeManifest.hash == manifest.hash)
        ).first()
        assert row is not None
        assert row.session_id == session_id
        assert Manifest.from_dict(row.content).hash == manifest.hash


def test_resolve_snapshot_immutable_after_config_edit(app):
    """An already-resolved manifest is unaffected by a later device template change."""
    with app.app_context():
        template_path = device_templates.create("snap-pod", _DEVICE_CONTENT).file_path

    session_id = _build_session(app, template_path)

    with app.app_context():
        manifest = manifests.resolve(session_id)
        original_hash = manifest.hash

    with app.app_context():
        device_templates.update(
            "snap-pod",
            {
                "type": "pod8206hr",
                "parameters": {
                    "preamp_gain": 100,
                    "sample_rate": 2000,
                    },
            },
        )

        row = db.session.scalars(
            db.select(RuntimeManifest).where(RuntimeManifest.hash == original_hash)
        ).first()
        assert row is not None
        recovered = Manifest.from_dict(row.content)
        assert recovered.hash == original_hash
        assert recovered.device_flows[0].parameters == {"preamp_gain": 10, "sample_rate": 2000}


def test_resolve_raises_on_missing_config_and_persists_nothing(app):
    """A session referencing a missing config raises UnresolvableSession; no row written."""
    with app.app_context():
        # Bypass import_config validation — create session with a raw orphaned reference.
        session = SessionRepository().create({
            "name": "Orphan Session",
            "device_flows": [{
                "device_config_id": 99999,
                "sink_type": "csv",
                "sink_location": "/data/out.csv",
                "nickname": "ghost-device",
            }],
        })
        session_id = session.id

        count_before = db.session.scalars(
            db.select(db.func.count()).select_from(RuntimeManifest)
        ).one()

        with pytest.raises(UnresolvableSession) as exc_info:
            manifests.resolve(session_id)

        assert exc_info.value.session_id == session_id
        assert exc_info.value.missing_config == "99999"

        count_after = db.session.scalars(
            db.select(db.func.count()).select_from(RuntimeManifest)
        ).one()
        assert count_after == count_before


def test_resolve_reproducible_hash(app):
    """Re-resolving the same session with unchanged configs yields the same manifest hash."""
    with app.app_context():
        template_path = device_templates.create("repro-pod", _DEVICE_CONTENT).file_path

    session_id = _build_session(app, template_path)

    with app.app_context():
        m1 = manifests.resolve(session_id)

    with app.app_context():
        m2 = manifests.resolve(session_id)

    assert m1.hash == m2.hash


# The canonical multi-sink descriptor fixture recorded for downstream packets
# (preflight/factory/integration): one source fanning out to a file sink, a
# service sink, and a plot sink, in order.
_MULTI_SINK_ENTRY = {
    "hardware_id": "004",
    "port": "/dev/ttyUSB1",
    "sinks": [
        {"sink_name": "raw-csv", "sink_type": "csv", "sink_location": "/data/multi.csv"},
        {
            "sink_name": "live",
            "sink_type": "quest",
            "sink_parameters": {"host": "localhost", "port": 9009, "measurement": "exp"},
        },
        {"sink_name": "scope", "sink_type": "plot"},
    ],
}


def test_resolve_multi_sink_source_to_ordered_v2_descriptors(app):
    """A canonical multi-sink source resolves to ordered v2 SinkConfig descriptors
    with stable source/sink identities; only the file sink gets a file_path, and
    the persisted manifest carries its session_id."""
    with app.app_context():
        template_path = device_templates.create("multi-pod", _DEVICE_CONTENT).file_path

    entry = {**_MULTI_SINK_ENTRY, "device_template_path": template_path}
    with app.app_context():
        session_id = session_config.import_config(
            {"name": "Multi", "policy": "recommend", "device_flows": [entry]}
        ).id

    with app.app_context():
        manifest = manifests.resolve(session_id)

        assert manifest.session_id == session_id
        assert len(manifest.device_flows) == 1
        df = manifest.device_flows[0]
        device_id = df.device_id
        assert device_id == "pod8206hr:004"

        # Order preserved; each sink keeps its source-local identity.
        assert [s.name for s in df.sinks] == ["raw-csv", "live", "scope"]
        assert [s.sink_id for s in df.sinks] == [
            f"{device_id}:raw-csv",
            f"{device_id}:live",
            f"{device_id}:scope",
        ]
        assert [s.type for s in df.sinks] == [SinkType.CSV, SinkType.QUEST, SinkType.PLOT]

        # Only the file sink carries a resolved file_path; service/plot sinks
        # never receive a fabricated one.
        assert df.sinks[0].parameters["file_path"] == "/data/multi.csv"
        assert "file_path" not in df.sinks[1].parameters
        assert "file_path" not in df.sinks[2].parameters

        # Round-trips through the persisted row unchanged.
        row = db.session.scalars(
            db.select(RuntimeManifest).where(RuntimeManifest.hash == manifest.hash)
        ).first()
        assert row is not None and row.session_id == session_id
        assert Manifest.from_dict(row.content) == manifest


def test_resolve_raises_session_not_found(app):
    with app.app_context(), pytest.raises(SessionNotFound):
        manifests.resolve(99999)


def test_resolve_raises_empty_session(app):
    with app.app_context():
        session = SessionRepository().create({"name": "Empty", "device_flows": []})
        with pytest.raises(EmptySession):
            manifests.resolve(session.id)


@pytest.mark.parametrize("old_port,new_port", [
    ("/dev/ttyUSB0", "/dev/ttyUSB5"), ("COM3", "COM7"),
])
def test_start_resolves_renumbered_hardware_and_preserves_history(app, monkeypatch, old_port, new_port):
    with app.app_context():
        template = device_templates.create("renumbered-pod", _DEVICE_CONTENT).file_path
    session_id = _build_session(app, template)
    ports = [SimpleNamespace(serial_number="002", device=old_port)]
    monkeypatch.setattr("serial.tools.list_ports.comports", lambda: ports)
    with app.app_context():
        old = manifests.resolve(session_id)
        ports[:] = [SimpleNamespace(serial_number="other", device=old_port),
                    SimpleNamespace(serial_number="002", device=new_port)]
        new = manifests.resolve(session_id)
        assert new.device_flows[0].port == new_port
        from app.models.device_config import DeviceConfig
        config = db.session.scalars(db.select(DeviceConfig).where(DeviceConfig.hardware_id == "002")).one()
        assert config.port == new_port
        assert new.device_flows[0].device_id == old.device_flows[0].device_id
        assert new.hash != old.hash
        row = db.session.scalars(db.select(RuntimeManifest).where(RuntimeManifest.hash == old.hash)).one()
        historical = Manifest.from_dict(row.content)
        assert historical.device_flows[0].port == old_port
        assert historical.hash == old.hash


@pytest.mark.parametrize("ports,message", [
    ([SimpleNamespace(serial_number="other", device="/dev/ttyUSB0")], "No serial port"),
    ([SimpleNamespace(serial_number="002", device="COM3"),
      SimpleNamespace(serial_number="002", device="COM7")], "Ambiguous"),
])
def test_start_rejects_unresolvable_serial_without_persisting(app, monkeypatch, ports, message):
    from app.domain.errors import InvalidSessionEntry
    with app.app_context():
        template = device_templates.create("missing-pod", _DEVICE_CONTENT).file_path
    session_id = _build_session(app, template)
    monkeypatch.setattr("serial.tools.list_ports.comports", lambda: ports)
    with app.app_context():
        with pytest.raises(InvalidSessionEntry, match=message):
            manifests.resolve(session_id)
        assert db.session.scalars(db.select(RuntimeManifest)).all() == []


def test_stop_resolution_does_not_probe_disconnected_hardware(app, monkeypatch):
    with app.app_context():
        template = device_templates.create("stopped-pod", _DEVICE_CONTENT).file_path
    session_id = _build_session(app, template)
    def forbidden():
        raise AssertionError("stop must not enumerate hardware")
    monkeypatch.setattr("serial.tools.list_ports.comports", forbidden)
    with app.app_context():
        manifests.resolve(session_id, validate_sink_locations=False)


def test_start_d2xx_retains_configured_driver_address(monkeypatch):
    # Exercise driver routing independently of dashboard template validation.
    config = SimpleNamespace(hardware_id="002", port="FT002", device_type="pod8206hr",
                             parameters={"use_d2xx": True}, nickname=None, source_template=None)
    monkeypatch.setattr(manifests._device_configs, "get_by_id", lambda _: config)
    monkeypatch.setattr(manifests, "lookup_device", lambda *args: SimpleNamespace(as_dict=lambda: config.parameters))
    def forbidden():
        raise AssertionError("D2XX must not enumerate OS serial ports")
    monkeypatch.setattr("serial.tools.list_ports.comports", forbidden)
    manifest = manifests._build_manifest(
        dataflow_id="test", session_name="test", policy="recommend", session_id_for_errors=1,
        flows=[{"device_config_id": 1, "sinks": [{"sink_name": "plot", "sink_type": "plot"}]}],
    )
    assert manifest.device_flows[0].port == "FT002"


def test_stop_reuses_original_manifest_after_database_port_refresh(app, monkeypatch):
    from app.domain.enums import DeviceType
    from app.services.device_ports import refresh_port
    with app.app_context():
        template = device_templates.create("history-pod", _DEVICE_CONTENT).file_path
    session_id = _build_session(app, template)
    with app.app_context():
        original = manifests.resolve(session_id)
        monkeypatch.setattr("serial.tools.list_ports.comports", lambda: [
            SimpleNamespace(serial_number="002", device="COM7"),
        ])
        refresh_port(DeviceType.POD8206HR, "002")
        stopped = manifests.resolve(session_id, validate_sink_locations=False)
        assert stopped.hash == original.hash
        assert stopped.device_flows[0].port == original.device_flows[0].port
        assert len(db.session.scalars(db.select(RuntimeManifest)).all()) == 1
