"""Verify physical channel conversion independently of display-label spelling."""

from types import SimpleNamespace

import numpy as np
import pytest
from app.models.output_file import OutputFile
from app.output.managed_pvfs_sink import ManagedPvfsSink

from Morelia.Devices import Preamp
from Morelia.Stream.source import MissingSample

LAYOUTS = [
    ("Preamp8407_SE", ["Bio", "EEG1", "EMG", "EEG2"]),
    ("Preamp8407_SL", ["Bio", "EEG1", "EMG", "EEG2"]),
    ("Preamp8407_SE3", ["Bio", "EEG1", "EEG3", "EEG2"]),
    ("Preamp8407_SE4", ["EEG4", "EEG1", "EEG3", "EEG2"]),
    ("Preamp8407_SE31M", ["EEG3", "EEG1", "EMG", "EEG2"]),
    ("Preamp8407_SE_2BIO", ["Bio1", "Bio2", "EMG", "EEG2"]),
    ("Preamp8407_SL_2BIO", ["Bio1", "Bio2", "EMG", "EEG2"]),
    ("Preamp8406_SE31M", ["EMG", "EEG1", "EEG3", "EEG2"]),
    ("Preamp8406_BIO", ["Bio", "NC", "NC", "NC"]),
    ("Preamp8406_2BIO", ["Bio1", "Bio2", "NC", "NC"]),
    ("Preamp8406_EEG2BIO", ["Bio1", "EEG1", "EMG", "Bio2"]),
    ("Preamp8406_SE", ["Bio", "EEG1", "EMG", "EEG2"]),
    ("Preamp8406_SL", ["Bio", "EEG1", "EMG", "EEG2"]),
    ("Preamp8406_SE3", ["Bio", "EEG1", "EEG3", "EEG2"]),
    ("Preamp8406_SE4", ["EEG4", "EEG1", "EEG3", "EEG2"]),
]


class Pod8401HR:
    sample_rate = 4

    def __init__(self, preamp):
        self.preamp = preamp


@pytest.mark.parametrize("preamp,labels", LAYOUTS)
def test_preamp_labels_keep_physical_positions_without_opening(
    tmp_path, preamp, labels
):
    path = tmp_path / "packet.pvfs"
    sink = ManagedPvfsSink(
        path=path, dataflow_id="physical", pod=Pod8401HR(getattr(Preamp, preamp))
    )
    frame = sink._frame_from_packet(SimpleNamespace(ch0=11, ch1=22, ch2=33, ch3=44))
    assert frame == [11, 22, 33, 44]
    assert sink.get_dict()["channels"] == labels
    assert not path.exists()
    assert not sink.opened


@pytest.mark.parametrize(
    "packet,field",
    [
        (SimpleNamespace(ch0=1, ch1=2, ch3=4), "ch2"),
        (SimpleNamespace(ch0=1, ch1=[2, 3], ch2=3, ch3=4), "ch1"),
        (SimpleNamespace(ch0=1, ch1=2, ch2="bad", ch3=4), "ch2"),
        (SimpleNamespace(ch0=1, ch1=2, ch2=3, ch3=None), "ch3"),
    ],
)
def test_bad_packet_rejected_before_allocation(tmp_path, app, packet, field):
    path = tmp_path / "invalid.pvfs"
    with app.app_context():
        sink = ManagedPvfsSink(
            path=path, dataflow_id="physical", pod=Pod8401HR(Preamp.Preamp8407_SE)
        )
        with pytest.raises(ValueError, match=field):
            sink.flush(1, packet)
        assert not path.exists()
        assert OutputFile.query.count() == 0


@pytest.mark.parametrize(
    "frame", [[1], [[1], 2], [np.array([1]), 2], [None, 2], "12", 1]
)
def test_bad_explicit_frame_rejected_before_allocation(tmp_path, app, frame):
    path = tmp_path / "invalid.pvfs"
    with app.app_context():
        sink = ManagedPvfsSink(
            path=path, dataflow_id="physical", channels=["X", "Y"], sample_rate=4
        )
        with pytest.raises(ValueError):
            sink.write_frame(frame)
        assert not path.exists()
        assert OutputFile.query.count() == 0


def test_row_missing_channel_is_not_a_zero_measurement(tmp_path, app):
    with app.app_context():
        sink = ManagedPvfsSink(
            path=tmp_path / "row.pvfs",
            dataflow_id="physical",
            channels=["X", "Y"],
            sample_rate=4,
        )
        with pytest.raises(ValueError, match="required channels: Y"):
            sink.write_row({"X": 1})
        assert OutputFile.query.count() == 0
        sink.write_row({"Y": 22, "X": 11})
        sink.write_frame([33, 44])
        sink.close()
        assert sink.record.row_offset == 2


@pytest.mark.parametrize("process", [False, True])
def test_packet_nan_placeholders_and_real_zero_read_back(tmp_path, app, process):
    from pvfs_tools.Core.pvfs_binding import HighTime
    from pvfs_tools.Core.pvfs_data_file import PvfsDataFile

    path = tmp_path / "nan.pvfs"
    with app.app_context():
        sink = ManagedPvfsSink(
            path=path,
            dataflow_id="physical",
            pod=Pod8401HR(Preamp.Preamp8407_SE),
            use_writer_process=process,
        )
        events = []
        sink.bind_recording_callback(events.append)
        sink.flush(1, MissingSample())
        assert events == []
        sink.flush(2, SimpleNamespace(ch0=0, ch1=12, ch2=13, ch3=14))
        sink.flush(3, SimpleNamespace(ch0=21, ch1=22, ch2=23, ch3=24))
        sink.flush(4, MissingSample())
        sink.flush(5, SimpleNamespace(ch0=31, ch1=32, ch2=33, ch3=34))
        sink.flush(
            6, SimpleNamespace(ch0=float("nan"), ch1=float("inf"), ch2=43, ch3=44)
        )
        sink.close()
        assert sink.record.row_offset == 6
    reader = PvfsDataFile()
    assert reader.open(str(path))
    try:
        assert sorted(
            reader.get_channel_names(),
            key=lambda name: reader.get_channel_info(name).id,
        ) == [
            "Bio",
            "EEG1",
            "EMG",
            "EEG2",
        ]
        for name, expected in zip(
            ["Bio", "EEG1", "EMG", "EEG2"],
            [
                [np.nan, 0, 21, np.nan, 31, 0],
                [np.nan, 12, 22, np.nan, 32, 0],
                [np.nan, 13, 23, np.nan, 33, 43],
                [np.nan, 14, 24, np.nan, 34, 44],
            ],
            strict=True,
        ):
            channel = reader.open_channel(name)
            _, values = channel.get_data(
                HighTime.from_seconds(channel.get_start_time().to_seconds() - 1),
                HighTime.from_seconds(channel.get_end_time().to_seconds() + 1),
            )
            np.testing.assert_allclose(values, expected, equal_nan=True)
    finally:
        reader.close()
