from __future__ import annotations

import hashlib
import math

import pytest
from app.output.pvfs_merger import open_pvfs_reader, read_channel_samples
from pvfs_tools.Core.pvfs_binding import HighTime
from pvfs_tools.Core.pvfs_data_file import PvfsDataFile


def _record(path, blocks, *, rate=4, checkpoint=False):
    writer = PvfsDataFile()
    assert writer.create(str(path))
    writer.set_experiment_info(name="reader test", start_time=HighTime(1735689600))
    channel = writer.create_channel("EEG1", data_rate=rate, unit="uV")
    channel._delta_time = HighTime.from_seconds(1.0 / rate)
    try:
        for offset, values in blocks:
            assert (
                channel.append_block(HighTime.from_seconds(1735689600 + offset), values)
                == 0
            )
            if checkpoint:
                writer.flush(synchronous=True)
    finally:
        assert writer.close() is True


@pytest.mark.parametrize(
    "blocks,expected_times,expected_values,rate,checkpoint",
    [
        ([(0, [7.0])], [0.0], [7.0], 4, False),
        (
            [(0, [1.0, 2.0, 3.0, 4.0]), (1, [5.0])],
            [0.0, 0.25, 0.5, 0.75, 1.0],
            [1.0, 2.0, 3.0, 4.0, 5.0],
            4,
            False,
        ),
        ([(0, [1.0, 2.0]), (0.5, [3.0])], [0.0, 0.25, 0.5], [1.0, 2.0, 3.0], 4, True),
        ([(0, [1.0]), (10, [2.0])], [0.0, 10.0], [1.0, 2.0], 4, False),
        (
            [(0, [0.0, float("nan")]), (0.5, [-3.0])],
            [0.0, 0.25, 0.5],
            [0.0, float("nan"), -3.0],
            4,
            True,
        ),
        ([], [], [], 4, False),
        (
            [(0, [1.0, 2.0, 3.0, 4.0])],
            [0.0, 10.0, 20.0, 30.0],
            [1.0, 2.0, 3.0, 4.0],
            0.1,
            False,
        ),
        (
            [(0, [float(i) for i in range(400)]), (1, [401.0])],
            [i / 400 for i in range(401)],
            [float(i) for i in range(400)] + [401.0],
            400,
            False,
        ),
    ],
)
def test_reads_exact_native_samples(
    tmp_path, blocks, expected_times, expected_values, rate, checkpoint
):
    path = tmp_path / "source.pvfs"
    _record(path, blocks, rate=rate, checkpoint=checkpoint)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    reader = PvfsDataFile()
    assert reader.open(str(path))
    try:
        times, values = read_channel_samples(reader.open_channel("EEG1"))
        assert times == pytest.approx(
            [1735689600 + t for t in expected_times], abs=1e-6, rel=0
        )
        assert len(values) == len(expected_values)
        for actual, expected in zip(values, expected_values):
            if math.isnan(expected):
                assert math.isnan(actual)
            else:
                assert actual == expected
    finally:
        reader.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


class _CorruptRead:
    def __init__(self, handle, target, *, truncate=False):
        self.handle = handle
        self.target = target
        self.cursor = 0
        self.truncate = truncate

    def seek(self, offset):
        self.cursor = offset
        return self.handle.seek(offset)

    def read(self, size):
        data = bytearray(self.handle.read(size))
        if self.cursor <= self.target < self.cursor + len(data):
            if self.truncate:
                data = data[:-1]
            else:
                data[self.target - self.cursor] ^= 1
        self.cursor += len(data)
        return bytes(data)

    def get_file_info(self):
        return self.handle.get_file_info()


@pytest.mark.parametrize(
    "attribute,offset,truncate,message",
    [
        ("_index_file", 0, False, "encoding"),
        ("_index_file", 1000, False, "index entry"),
        ("_index_file", 1040, False, "index entry"),
        ("_data_file", 0, False, "block header"),
        ("_data_file", 32, False, "checksum"),
        ("_data_file", 32, True, "truncated"),
    ],
)
def test_rejects_corrupt_native_reads(tmp_path, attribute, offset, truncate, message):
    path = tmp_path / "source.pvfs"
    _record(path, [(0, [1.0, 2.0, 3.0, 4.0]), (1, [5.0])])
    reader = PvfsDataFile()
    assert reader.open(str(path))
    channel = reader.open_channel("EEG1")
    original = getattr(channel, attribute)
    try:
        setattr(channel, attribute, _CorruptRead(original, offset, truncate=truncate))
        with pytest.raises(ValueError, match=message):
            read_channel_samples(channel)
        setattr(channel, attribute, original)
        assert read_channel_samples(channel)[1] == [1.0, 2.0, 3.0, 4.0, 5.0]
    finally:
        setattr(channel, attribute, original)
        reader.close()


def _record_duplicates(path):
    writer = PvfsDataFile()
    assert writer.create(str(path))
    writer.set_experiment_info(name="duplicate labels", start_time=HighTime(1735689600))
    opened = []
    for name in ["Bio", "NC", "NC", "NC"]:
        channel = writer.create_channel(name, data_rate=4, unit="uV")
        channel._delta_time = HighTime.from_seconds(0.25)
        opened.append(channel)
    for number, name in enumerate(["Bio", "NC", "NC", "NC"]):
        assert (
            writer._indexed_data_files[name].append_block(
                HighTime(1735689600), [10.0 * number + 1.0, 10.0 * number + 2.0]
            )
            == 0
        )
    assert writer.close() is True
    for channel in opened:
        channel.close()


@pytest.mark.parametrize("kind", ["duplicate", "ordinary", "nan"])
@pytest.mark.parametrize("fail_read", [False, True])
def test_reader_context_preserves_sources_and_releases_handles(
    tmp_path, kind, fail_read
):
    path = tmp_path / "source.pvfs"
    if kind == "duplicate":
        _record_duplicates(path)
    else:
        values = [1.0, float("nan"), 3.0] if kind == "nan" else [1.0, 2.0, 3.0]
        _record(path, [(0, values)])
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    original_flush = PvfsDataFile.flush
    reader = None
    handles = []
    container = None
    try:
        with open_pvfs_reader(path) as reader:
            assert type(reader) is PvfsDataFile and reader.is_read_only
            container = reader._pvfs
            for channel in reader._indexed_data_files.values():
                handles.extend([channel._index_file, channel._data_file])
            if kind == "duplicate":
                assert list(reader.get_channel_names()) == ["Bio", "NC", "NC", "NC"]
            else:
                _, result = read_channel_samples(reader.open_channel("EEG1"))
                assert len(result) == 3
                if kind == "nan":
                    assert math.isnan(result[1])
            if fail_read:
                raise RuntimeError("injected consumer failure")
    except RuntimeError as exc:
        assert fail_read and str(exc) == "injected consumer failure"
    assert reader is not None and reader._database is None and reader._pvfs is None
    assert container is not None and container._wrapper is None
    assert handles and all(handle._closed for handle in handles)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert PvfsDataFile.flush is original_flush


def test_reader_context_rejects_native_open_failure(tmp_path):
    path = tmp_path / "corrupt.pvfs"
    path.write_bytes(b"not a PVFS recording")
    before = path.read_bytes()
    with (
        pytest.raises(ValueError, match="unreadable or corrupt"),
        open_pvfs_reader(path),
    ):
        pytest.fail("invalid native recording was opened")
    assert path.read_bytes() == before


def test_reader_context_rejects_false_close_after_cleanup(tmp_path):
    path = tmp_path / "source.pvfs"
    _record(path, [(0, [1.0, 2.0])])
    with (
        pytest.raises(ExceptionGroup, match="PVFS reader cleanup failed"),
        open_pvfs_reader(path) as reader,
    ):
        native_close = reader.close

        def false_close():
            assert native_close() is True
            return False

        reader.close = false_close
