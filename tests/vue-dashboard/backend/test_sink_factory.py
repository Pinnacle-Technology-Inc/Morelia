"""Packet 13 — worker sink factory: type dispatch, identity, and cleanup.

These tests exercise the factory in isolation. CSV construction is verified two
ways: against the real deferred-open ``ManagedCsvSink`` (whose ``__init__`` does
no filesystem/DB work, so no app/DB fixture is needed) and against a lightweight
fake that records close ordering for the sibling-cleanup cases.
"""

from __future__ import annotations

import pytest

from app.domain.enums import SinkType
from app.output.managed_csv_sink import ManagedCsvSink
from app.output.plot_sink import ManagedPlotSink
from app.runtime_child.sink_factory import (
    RuntimeContext,
    SinkConstructionError,
    build_sink,
    build_sinks,
)
from app.runtime_host.manifest import SinkConfig

_FIELDS = ["time", "EEG1", "EEG2", "EEG3/EMG", "TTL1", "TTL2", "TTL3", "TTL4"]

# Every approved SinkType now has a real builder (PLOT landed in packet 27).
# The durable factory contract below asserts each type either returns an adapter
# or raises a sink-addressed SinkConstructionError — never a bare crash.
_ALL_SINK_TYPES = list(SinkType)


def _csv_config(path: str, *, sink_id: str = "pod8206hr:hw1:csv") -> SinkConfig:
    return SinkConfig(
        sink_id=sink_id,
        name=sink_id.rsplit(":", 1)[-1],
        type=SinkType.CSV,
        parameters={"file_path": path},
    )


def _minimal_config(sink_type: SinkType, *, sink_id: str) -> SinkConfig:
    """Minimal registry-valid parameters for each approved type."""
    parameters: dict[str, object]
    if sink_type in (SinkType.CSV, SinkType.EDF, SinkType.PVFS):
        parameters = {"file_path": f"/tmp/{sink_id}.out"}
    elif sink_type is SinkType.INFLUX:
        parameters = {"api_token_env": "PINNACLE_INFLUX_TOKEN"}
    else:  # QUEST, PLOT
        parameters = {}
    return SinkConfig(sink_id=sink_id, name=sink_type.value, type=sink_type, parameters=parameters)


def _ctx(**overrides) -> RuntimeContext:
    base = dict(
        dataflow_id="df-1",
        device_id="pod8206hr:hw1",
        schema_hash="hash-abc",
        csv_sink_class=ManagedCsvSink,
        csv_fieldnames=tuple(_FIELDS),
    )
    base.update(overrides)
    return RuntimeContext(**base)


# ---------------------------------------------------------------------------
# CSV: acceptance criterion 1 — constructs the managed adapter, deferred-open.
# ---------------------------------------------------------------------------


def test_build_sink_csv_builds_deferred_open_managed_sink(tmp_path):
    path = str(tmp_path / "run.csv")
    sink = build_sink(_csv_config(path, sink_id="pod8206hr:hw1:extra"), object(), _ctx())

    assert isinstance(sink, ManagedCsvSink)
    assert sink.opened is False  # SINK-21: construction opens nothing
    d = sink.get_dict()
    assert d["path"] == path
    assert d["sink_id"] == "pod8206hr:hw1:extra"
    assert d["dataflow_id"] == "df-1"
    assert d["schema_hash"] == "hash-abc"
    assert d["device_id"] == "pod8206hr:hw1"
    assert d["fieldnames"] == _FIELDS


def test_build_sink_csv_missing_file_path_raises_valueerror():
    # A CSV descriptor with no resolved path is a caller/resolver bug, surfaced
    # as ValueError (not a typed dependency/not-implemented outcome).
    cfg = SinkConfig(sink_id="s", name="s", type=SinkType.CSV, parameters={})
    with pytest.raises(ValueError, match="no resolved file_path"):
        build_sink(cfg, object(), _ctx())


def test_build_sink_csv_requires_injected_class_and_fieldnames(tmp_path):
    path = str(tmp_path / "run.csv")
    with pytest.raises(SinkConstructionError, match="csv_sink_class"):
        build_sink(_csv_config(path), object(), _ctx(csv_sink_class=None))
    with pytest.raises(SinkConstructionError, match="csv_fieldnames"):
        build_sink(_csv_config(path), object(), _ctx(csv_fieldnames=None))


# ---------------------------------------------------------------------------
# Acceptance criterion 2 — every approved type has an explicit branch;
# build_sink either returns an adapter or raises a sink-addressed error.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sink_type", _ALL_SINK_TYPES)
def test_build_sink_every_type_returns_adapter_or_sink_addressed_error(sink_type):
    sink_id = f"pod8206hr:hw1:{sink_type.value}"
    cfg = _minimal_config(sink_type, sink_id=sink_id)

    try:
        sink = build_sink(cfg, object(), _ctx())
    except SinkConstructionError as err:
        # Sink-addressed: the failure names the exact sink and its type.
        assert err.sink_id == sink_id
        assert err.sink_type is sink_type
        return

    # Adapter path: construction succeeded with a lifecycle-shaped object.
    assert sink is not None
    assert getattr(sink, "sink_id", None) in (sink_id, None) or hasattr(sink, "get_dict")


def test_build_sink_plot_builds_deferred_open_managed_sink():
    sink = build_sink(
        _minimal_config(SinkType.PLOT, sink_id="pod8206hr:hw1:plot"),
        object(),
        _ctx(),
    )
    assert isinstance(sink, ManagedPlotSink)
    assert sink.opened is False
    assert sink.sink_id == "pod8206hr:hw1:plot"


def test_build_sink_unknown_descriptor_raises_construction_error():
    from types import SimpleNamespace

    bogus = SimpleNamespace(sink_id="weird", type="not-a-sink-type", parameters={})
    with pytest.raises(SinkConstructionError, match="unknown sink descriptor"):
        build_sink(bogus, object(), _ctx())


# ---------------------------------------------------------------------------
# build_sinks — order/identity preserved; siblings closed in reverse on failure.
# ---------------------------------------------------------------------------


class _RecordingSink:
    """Minimal lifecycle-shaped sink that records close ordering."""

    def __init__(self, close_log: list[str], *, sink_id: str, **_kwargs) -> None:
        self.sink_id = sink_id
        self._close_log = close_log
        self.closed = False

    def close(self) -> None:
        self.closed = True
        self._close_log.append(self.sink_id)


def test_build_sinks_preserves_manifest_order_and_identity(tmp_path):
    configs = [
        _csv_config(str(tmp_path / "a.csv"), sink_id="dev:a"),
        _csv_config(str(tmp_path / "b.csv"), sink_id="dev:b"),
        _csv_config(str(tmp_path / "c.csv"), sink_id="dev:c"),
    ]
    sinks = build_sinks(configs, object(), _ctx())

    assert [s.get_dict()["sink_id"] for s in sinks] == ["dev:a", "dev:b", "dev:c"]
    assert all(isinstance(s, ManagedCsvSink) for s in sinks)


def test_build_sinks_closes_created_siblings_in_reverse_on_failure(tmp_path):
    close_log: list[str] = []
    # Two buildable CSV siblings, then a CSV whose injected class raises.
    # Failure injection stays type-agnostic now that every SinkType builds.
    configs = [
        _csv_config(str(tmp_path / "a.csv"), sink_id="dev:a"),
        _csv_config(str(tmp_path / "b.csv"), sink_id="dev:b"),
        _csv_config(str(tmp_path / "boom.csv"), sink_id="dev:boom"),
    ]

    def _selective_csv(**kw):
        if kw.get("sink_id") == "dev:boom":
            raise RuntimeError("injected CSV construction failure")
        return _RecordingSink(close_log, **kw)

    with pytest.raises(Exception) as excinfo:
        build_sinks(configs, object(), _ctx(csv_sink_class=_selective_csv))

    # Original construction failure propagates; already-built siblings close
    # newest-first before the raise.
    assert "injected CSV construction failure" in str(excinfo.value)
    assert close_log == ["dev:b", "dev:a"]


def test_build_sinks_reports_cleanup_failures_as_secondary_diagnostics(tmp_path):
    close_log: list[str] = []

    class _BadCloseSink(_RecordingSink):
        def close(self) -> None:
            self._close_log.append(self.sink_id)
            raise RuntimeError(f"close boom for {self.sink_id}")

    def _factory(**kw):
        if kw.get("sink_id") == "dev:boom":
            raise RuntimeError("injected CSV construction failure")
        return _BadCloseSink(close_log, **kw)

    configs = [
        _csv_config(str(tmp_path / "a.csv"), sink_id="dev:a"),
        _csv_config(str(tmp_path / "boom.csv"), sink_id="dev:boom"),
    ]

    with pytest.raises(Exception) as excinfo:
        build_sinks(configs, object(), _ctx(csv_sink_class=_factory))

    err = excinfo.value
    # Original construction failure is preserved as the raised cause...
    assert "injected CSV construction failure" in str(err)
    # ...and the sibling cleanup failure is attached as secondary diagnostics.
    assert hasattr(err, "sink_cleanup_failures")
    failed_sinks = [sink.sink_id for sink, _exc in err.sink_cleanup_failures]
    assert failed_sinks == ["dev:a"]
    assert close_log == ["dev:a"]
