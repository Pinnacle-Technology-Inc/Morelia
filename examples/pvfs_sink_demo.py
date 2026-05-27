"""
Demonstrate PvfsSink by streaming simulated 8206HR-style data to a PVFS file.

This script does NOT require hardware. It creates a Pod8206HR with a dummy port,
sets a fixed sample rate, and feeds synthetic DataPacket8206HR packets (e.g. sine wave)
into PvfsSink. Use it to verify that the PVFS sink creates a valid .pvfs file
with experiment.db3 and indexed channels.

Usage:
  python pvfs_sink_demo.py [--output OUTPUT.pvfs] [--duration SECONDS] [--rate HZ]
  (default: demo_pvfs_sink.pvfs, 5 s, 400 Hz)

After running, open the output .pvfs in Sirenia or run the **pypvfs** test suite against the file (see the [pypvfs](https://pypi.org/project/pypvfs/) repository).
"""

import math
import sys
from pathlib import Path

# Allow running this script from a git clone without an editable install (optional).
_examples_dir = Path(__file__).resolve().parent
_project_root = _examples_dir.parent
_src = _project_root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

import Morelia.packet.conversion as conv
from Morelia.Devices import Pod8206HR
from Morelia.Stream.sink import PvfsSink
from Morelia.packet.data import DataPacket8206HR


class MockPod8206HR(Pod8206HR):
    """Minimal mock Pod8206HR for demos that bypasses queue manager initialization."""
    def __init__(self, sample_rate: int = 400, preamp_gain: int = 10):
        # Skip parent __init__ to avoid queue manager connection
        # Set minimal attributes needed by PvfsSink
        # Use _device_name directly to avoid property setter recursion bug
        self._device_name = "Mock8206HR"
        self._sample_rate = (sample_rate,)
        self._preamp_gain = preamp_gain
    
    @property
    def sample_rate(self) -> int:
        return self._sample_rate[0]
    
    @sample_rate.setter
    def sample_rate(self, rate: int) -> None:
        self._sample_rate = (rate,)


def uV_to_raw_16bit(uV: float, preamp_gain: int) -> int:
    """Convert microvolts to 8206HR raw 16-bit value (inverse of get_primary_channel_value)."""
    total_gain = preamp_gain * 50.2918
    real_voltage = uV / 1e6
    voltage_adc = real_voltage * total_gain + 2.048
    value = voltage_adc / 4.096 * 65535
    return max(0, min(65535, int(round(value))))


def make_8206_packet(
    ch0_uV: float, ch1_uV: float, ch2_uV: float,
    ttl_byte: int, packet_num: int, preamp_gain: int = 10,
) -> bytes:
    """Build 16-byte 8206HR data packet (STX + payload + checksum + ETX)."""
    stx = b"\x02"
    etx = b"\x03"
    command_number_bytes = conv.int_to_ascii_bytes(180, 4)
    packet_num_bytes = conv.int_to_binary_bytes(packet_num, 1)
    ttl_bytes = conv.int_to_binary_bytes(ttl_byte & 0xFF, 1)
    ch0_bytes = conv.int_to_binary_bytes(
        uV_to_raw_16bit(ch0_uV, preamp_gain), 2, conv.Endianness.LITTLE
    )
    ch1_bytes = conv.int_to_binary_bytes(
        uV_to_raw_16bit(ch1_uV, preamp_gain), 2, conv.Endianness.LITTLE
    )
    ch2_bytes = conv.int_to_binary_bytes(
        uV_to_raw_16bit(ch2_uV, preamp_gain), 2, conv.Endianness.LITTLE
    )
    payload = command_number_bytes + packet_num_bytes + ttl_bytes + ch0_bytes + ch1_bytes + ch2_bytes
    checksum = conv.int_to_ascii_bytes(sum(payload) & 0xFF, 2)
    return stx + payload + checksum + etx


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Demo PvfsSink with simulated 8206HR data")
    parser.add_argument(
        "--output", "-o",
        default="demo_pvfs_sink.pvfs",
        help="Output PVFS file path (default: demo_pvfs_sink.pvfs)",
    )
    parser.add_argument(
        "--duration", "-d",
        type=float,
        default=5.0,
        metavar="SEC",
        help="Simulated recording duration in seconds (default: 5)",
    )
    parser.add_argument(
        "--rate", "-r",
        type=float,
        default=400.0,
        metavar="HZ",
        help="Sample rate in Hz (default: 400)",
    )
    parser.add_argument(
        "--gain", "-g",
        type=int,
        default=10,
        choices=[10, 100],
        help="Preamplifier gain (default: 10)",
    )
    args = parser.parse_args()

    # Use mock pod to avoid queue manager initialization (not needed for demo)
    pod = MockPod8206HR(sample_rate=int(args.rate), preamp_gain=args.gain)

    output_path = Path(args.output)
    n_samples = int(args.duration * args.rate)
    sample_rate = args.rate

    print(f"Writing {n_samples} samples ({args.duration} s @ {sample_rate} Hz) to {output_path}")

    with PvfsSink(str(output_path), pod) as sink:
        for i in range(n_samples):
            t = i / sample_rate
            # Simple sine waves (e.g. 10 Hz, ±50 uV) so the file has recognizable content
            ch0_uV = 50.0 * math.sin(2 * math.pi * 10 * t)
            ch1_uV = 50.0 * math.sin(2 * math.pi * 10 * t + 0.5)
            ch2_uV = 30.0 * math.sin(2 * math.pi * 5 * t)
            ttl_byte = 0x80 if (i % 100) < 50 else 0  # simple TTL pattern
            raw = make_8206_packet(ch0_uV, ch1_uV, ch2_uV, ttl_byte, i % 256, args.gain)
            packet = DataPacket8206HR(raw, args.gain)
            sink.flush(i, packet)

    print(f"Done. PVFS file: {output_path}")
    if output_path.exists():
        print(f"  Size: {output_path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
