"""Real serializer/packet checks; only hardware construction and I/O failure vary."""

import csv
import io
import subprocess
import sys

import pytest

from app.output.managed_csv_sink import _CsvRecoveryAdapter
from Morelia.Devices import Pod8206HR, Pod8274D, Pod8401HR, Preamp
from Morelia.packet import PrimaryChannelMode, SecondaryChannelMode
from Morelia.packet.data.data_packet_8206hr import DataPacket8206HR
from Morelia.packet.data.data_packet_8274D import DataPacket8274D
from Morelia.packet.data.data_packet_8401hr import DataPacket8401HR
from Morelia.Stream.sink.csv_sink import CSVSink
from Morelia.Stream.source import MissingSample


HEADERS = {
    Pod8206HR: ("time", "EEG1", "EEG2", "EEG3/EMG", "TTL1", "TTL2", "TTL3", "TTL4"),
    Pod8401HR: ("time", "Bio", "EEG1", "EMG", "EEG2", "aEXT0", "aEXT1",
                "aTTL1", "aTTL2", "aTTL3", "aTTL4"),
    Pod8274D: ("time", "Ch5", "Ch6", "Ch7"),
}


def make_pod(device):
    pod = object.__new__(device)
    pod._preamp = Preamp.Preamp8407_SE
    pod._sample_rate = 1000
    return pod


def packet_8401():
    return DataPacket8401HR(
        preamp_gain=(10,) * 4, ss_gain=(5,) * 4,
        primary_channel_modes=(PrimaryChannelMode.EEG_EMG,) * 4,
        secondary_channel_modes=(SecondaryChannelMode.DIGITAL,) * 6,
        raw_packet=bytes(range(31)),
    )


def packet_8274():
    raw = bytearray(259)
    for offset, (channel, value) in enumerate(
        ((5, 100), (6, 200), (7, 300), (5, 400), (6, 500), (7, 600))
    ):
        start = 16 + 2 * offset
        raw[start:start + 2] = ((channel << 12) | value).to_bytes(2, "little")
    return DataPacket8274D(bytes(raw))


def make_adapter(device, target):
    return _CsvRecoveryAdapter(pod=make_pod(device), target=target, fieldnames=HEADERS[device])


def test_import_does_not_load_morelia():
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import app.output.managed_csv_sink; "
         "assert not any(k == 'Morelia' or k.startswith('Morelia.') for k in sys.modules)"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_original_api_has_no_dashboard_extensions():
    assert not hasattr(CSVSink, "fieldnames")
    assert not hasattr(CSVSink, "open_stream")
    assert not hasattr(CSVSink, "rows_written")


def test_borrowed_target_preserves_prefix_and_never_owns_lifecycle(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("adapter invoked a file ownership operation")

    class Target(io.StringIO):
        flush = forbidden
        close = forbidden

    stream = Target(newline="")
    prefix = "time,Ch5,Ch6,Ch7\r\n0,1,2,3\r\n"
    stream.write(prefix)
    monkeypatch.setattr(CSVSink, "__enter__", forbidden)
    monkeypatch.setattr(CSVSink, "__exit__", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    adapter = make_adapter(Pod8274D, stream)
    assert stream.getvalue() == prefix
    assert adapter.rows_written == 0
    assert not hasattr(adapter, "__enter__") and not hasattr(adapter, "__exit__")
    adapter.write_packet(1, MissingSample())
    assert stream.getvalue() == prefix + "1,,,\r\n"
    assert adapter.rows_written == 1
    assert not stream.closed


@pytest.mark.parametrize("device", list(HEADERS))
def test_validation_rejects_bad_schema_before_target_use(device):
    class UnusableTarget:
        @property
        def write(self):
            pytest.fail("validation must precede writer allocation")

    pod = make_pod(device)
    with pytest.raises(ValueError, match="fieldnames"):
        _CsvRecoveryAdapter(pod=pod, target=UnusableTarget(), fieldnames=("wrong",))
    assert _CsvRecoveryAdapter.validate(pod=pod, fieldnames=HEADERS[device]) is None


def test_unsupported_device_rejected():
    with pytest.raises(ValueError, match="unsupported CSV device"):
        _CsvRecoveryAdapter.validate(pod=object(), fieldnames=("time",))


def test_8401_literal_channel_mapping_and_missing_values():
    stream = io.StringIO(newline="")
    adapter = make_adapter(Pod8401HR, stream)
    packet = packet_8401()
    adapter.write_packet(100, packet)
    adapter.write_packet(101, MissingSample())
    rows = list(csv.DictReader(io.StringIO(stream.getvalue()), fieldnames=HEADERS[Pod8401HR]))
    assert rows[0]["Bio"] == str(packet.ch0)
    assert rows[0]["EEG1"] == str(packet.ch1)
    assert rows[0]["EMG"] == str(packet.ch2)
    assert rows[0]["EEG2"] == str(packet.ch3)
    assert rows[1] == dict(zip(HEADERS[Pod8401HR], ["101"] + [""] * 10))
    assert adapter.rows_written == 2


def test_8206_serializes_all_eight_values_and_missing_values():
    stream = io.StringIO(newline="")
    adapter = make_adapter(Pod8206HR, stream)
    packet = DataPacket8206HR(bytes(range(16)), preamp_gain=10)
    adapter.write_packet(123, packet)
    adapter.write_packet(124, MissingSample())
    rows = list(csv.reader(io.StringIO(stream.getvalue())))
    assert rows == [
        list(map(str, (123, packet.ch0, packet.ch1, packet.ch2,
                       packet.ttl1, packet.ttl2, packet.ttl3, packet.ttl4))),
        ["124"] + [""] * 7,
    ]
    assert adapter.rows_written == 2


def test_8274_counts_expanded_and_missing_rows():
    stream = io.StringIO(newline="")
    adapter = make_adapter(Pod8274D, stream)
    packet = packet_8274()
    adapter.write_packet(1_000_000, packet)
    adapter.write_packet(3_000_000, MissingSample())
    rows = list(csv.reader(io.StringIO(stream.getvalue())))
    assert rows == [
        list(map(str, (1_000_000, packet.ch5[0], packet.ch6[0], packet.ch7[0]))),
        list(map(str, (2_000_000, packet.ch5[1], packet.ch6[1], packet.ch7[1]))),
        ["3000000", "", "", ""],
    ]
    assert adapter.rows_written == 3


def test_8274_empty_burst_has_no_rows():
    stream = io.StringIO(newline="")
    adapter = make_adapter(Pod8274D, stream)
    adapter.write_packet(1, DataPacket8274D(bytes(259)))
    assert stream.getvalue() == ""
    assert adapter.rows_written == 0


@pytest.mark.parametrize("successful_rows", [0, 1])
def test_failed_burst_preserves_only_completed_row_count(successful_rows):
    class FailingTarget(io.StringIO):
        calls = 0

        def write(self, value):
            if self.calls == successful_rows:
                raise OSError("injected write failure")
            self.calls += 1
            return super().write(value)

    stream = FailingTarget(newline="")
    adapter = make_adapter(Pod8274D, stream)
    with pytest.raises(OSError, match="injected write failure"):
        adapter.write_packet(1_000_000, packet_8274())
    assert adapter.rows_written == successful_rows
    assert len(list(csv.reader(io.StringIO(stream.getvalue())))) == successful_rows
    assert not stream.closed
