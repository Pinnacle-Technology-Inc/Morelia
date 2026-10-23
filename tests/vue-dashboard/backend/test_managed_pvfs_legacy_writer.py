"""Regression checks for legacy delegation and cleanup after partial native setup."""

import pytest
from app.models.output_file import OutputFile
from app.output.managed_pvfs_sink import ManagedPvfsSink, ManagedPvfsSinkError


@pytest.mark.parametrize("rate", [0, -1, float("nan"), float("inf"), "invalid"])
def test_invalid_rate_fails_before_allocation(tmp_path, app, rate):
    path = tmp_path / "invalid.pvfs"
    with app.app_context():
        sink = ManagedPvfsSink(
            path=path, dataflow_id="legacy", channels=["A"], sample_rate=rate
        )
        with pytest.raises(ManagedPvfsSinkError, match="finite and positive"):
            sink.open()
        assert not path.exists()
        assert OutputFile.query.count() == 0
        with pytest.raises(ManagedPvfsSinkError, match="startup failed"):
            sink.close()


@pytest.mark.parametrize(
    "channels,units", [([""], ["uV"]), ([None], ["uV"]), (["A", "B"], ["uV"])]
)
def test_invalid_layout_fails_before_allocation(tmp_path, app, channels, units):
    path = tmp_path / "invalid.pvfs"
    with app.app_context():
        sink = ManagedPvfsSink(
            path=path,
            dataflow_id="legacy",
            channels=channels,
            units=units,
            sample_rate=4,
        )
        with pytest.raises(ManagedPvfsSinkError):
            sink.open()
        assert not path.exists()
        assert OutputFile.query.count() == 0
        with pytest.raises(ManagedPvfsSinkError, match="startup failed"):
            sink.close()


@pytest.mark.parametrize("cleanup_fails_once", [False, True])
def test_partial_legacy_setup_retains_owner_and_closes_without_reopening(
    tmp_path,
    app,
    monkeypatch,
    cleanup_fails_once,
):
    from pvfs_tools.Core.pvfs_data_file import PvfsDataFile

    create_channel = PvfsDataFile.create_channel
    native_close = PvfsDataFile.close
    close_calls = []
    setup_failed = False

    def fail_second_channel(native, name, **kwargs):
        nonlocal setup_failed
        if name == "B":
            setup_failed = True
            raise OSError("injected second channel setup failure")
        return create_channel(native, name, **kwargs)

    def close(native):
        if not setup_failed:
            return native_close(native)
        close_calls.append(native)
        if cleanup_fails_once and len(close_calls) == 1:
            return False
        return native_close(native)

    monkeypatch.setattr(PvfsDataFile, "create_channel", fail_second_channel)
    monkeypatch.setattr(PvfsDataFile, "close", close)
    with app.app_context():
        sink = ManagedPvfsSink(
            path=tmp_path / "partial.pvfs",
            dataflow_id="legacy",
            channels=["A", "B"],
            sample_rate=4,
        )
        with pytest.raises(ManagedPvfsSinkError, match="second channel setup failure"):
            sink.open()
        native = sink._legacy_writer._pvfs_data
        assert close_calls == [native]
        assert sink._legacy_state["closed"] is not cleanup_fails_once
        assert sink.record.acquisition_state == "interrupted"
        for operation in [
            sink.open,
            sink.recover,
            sink.flush,
            lambda: sink.flush(1, object()),
            lambda: sink.write_frame([1, 2]),
        ]:
            with pytest.raises(ManagedPvfsSinkError):
                operation()
        with pytest.raises(ManagedPvfsSinkError, match="second channel setup failure"):
            sink.close()
        assert sink._legacy_state["closed"]
        assert len(close_calls) == (2 if cleanup_fails_once else 1)
        assert OutputFile.query.count() == 1


def test_native_flush_failure_keeps_confirmed_count_and_never_replays(
    tmp_path, app, monkeypatch
):
    with app.app_context():
        sink = ManagedPvfsSink(
            path=tmp_path / "flush-fails.pvfs",
            dataflow_id="legacy",
            channels=["A", "B"],
            sample_rate=2,
        ).open()
        events = []
        sink.bind_recording_callback(events.append)
        sink.write_frame([1, 11])
        sink.write_frame([2, 12])
        assert len(events) == 1
        native = sink._legacy_writer._pvfs_data
        original_flush = native.flush

        def fail_flush(synchronous=True):
            raise OSError("injected flush failure after append")

        monkeypatch.setattr(native, "flush", fail_flush)
        sink.write_frame([3, 13])
        with pytest.raises(OSError, match="after append"):
            sink.write_frame([4, 14])
        assert sink._legacy_writer._samples_written == 4
        assert sink.record.row_offset == 2
        assert len(events) == 1
        monkeypatch.setattr(native, "flush", original_flush)
        with pytest.raises(ManagedPvfsSinkError, match="unavailable"):
            sink.write_frame([5, 15])
        with pytest.raises(ManagedPvfsSinkError, match="after append"):
            sink.close()
        assert sink._legacy_writer._samples_written == 4
        assert sink.record.row_offset == 2
        assert sink.record.acquisition_state == "interrupted"
        assert len(events) == 1
