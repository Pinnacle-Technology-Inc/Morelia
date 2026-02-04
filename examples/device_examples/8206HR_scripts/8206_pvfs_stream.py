"""
Stream 8206HR data to a PVFS file using the Morelia data collection pipeline.

Uses D2XX direct USB; follows the same pattern as examples/d2xx_example.py
(use device serial as port so the queue manager works). Assumes the 8206HR
is the only connected device, or use --device to pick by index/serial.
Output is compatible with the standard Sirenia data format (experiment.db3 + indexed channels).

Usage:
  python 8206_pvfs_stream.py [--output OUTPUT.pvfs] [--duration SECONDS] [--device INDEX]
  (default: output_8206.pvfs, run until Ctrl+C; device 0 = first D2XX device)

Requires: 8206HR connected via USB; D2XX drivers and ftd2xx (Windows) or pylibftdi (Linux/Mac).
"""

from pathlib import Path
import sys

# Add project src so Morelia and pvfs_tools are importable
_examples_dir = Path(__file__).resolve().parent
_device_examples = _examples_dir.parent
_examples_root = _device_examples.parent
_project_root = _examples_root.parent
_src = _project_root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from Morelia.Devices import Pod8206HR
from Morelia.Stream.sink import PvfsSink
from Morelia.Stream.data_flow import DataFlow


def list_d2xx_devices():
    """List all available FTDI D2XX devices (same as d2xx_example.py)."""
    try:
        from Morelia.Devices.SerialPorts.d2xx_helpers import list_d2xx_devices
        devices = list_d2xx_devices()
        print("Available D2XX devices:")
        for dev in devices:
            print(f"  Index {dev['index']}: {dev['description']} (Serial: {dev['serial']})")
        return devices
    except ImportError:
        print("D2XX support not available. Install ftd2xx (Windows) or pylibftdi (Linux/Mac).")
        return []


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Stream 8206HR data to a PVFS file (D2XX)")
    parser.add_argument(
        "--output", "-o",
        default="output_8206.pvfs",
        help="Output PVFS file path (default: output_8206.pvfs)",
    )
    parser.add_argument(
        "--device", "-p",
        default=0,
        help="D2XX device index 0,1,... (default: 0, first device). Uses device serial for queue manager.",
    )
    parser.add_argument(
        "--duration", "-d",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Record for SECONDS then stop (default: run until stop_collection)",
    )
    parser.add_argument(
        "--preamp-gain",
        type=int,
        default=100,
        choices=[10, 100],
        help="Preamp gain for 8206HR (default: 100)",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=115200,
        help="Baud rate for D2XX (default: 115200)",
    )
    args = parser.parse_args()

    # Match d2xx_example.py: list devices and use serial as port so queue manager gets a string key
    devices = list_d2xx_devices()
    if not devices:
        print("No D2XX devices found or D2XX not available.", file=sys.stderr)
        print("Install ftd2xx (Windows) or pylibftdi (Linux/Mac) and ensure 8206HR is connected.", file=sys.stderr)
        sys.exit(1)

    try:
        idx = int(args.device) if str(args.device).strip().isdigit() else 0
    except (TypeError, ValueError):
        idx = 0
    if idx < 0 or idx >= len(devices):
        print(f"Device index {idx} out of range (0..{len(devices)-1}).", file=sys.stderr)
        sys.exit(1)

    device_serial = devices[idx]["serial"]
    if isinstance(device_serial, bytes):
        device_serial = device_serial.decode("utf-8")
    port = device_serial  # Use serial so queue server registers get_write_queue_<serial>
    print(f"Using D2XX device index {idx}: {device_serial}")

    pod = Pod8206HR(
        port=port,
        preamp_gain=args.preamp_gain,
        baudrate=args.baudrate,
        use_d2xx=True,
    )
    pvfs_sink = PvfsSink(args.output, pod)
    mapping = [(pod, [pvfs_sink])]
    flowgraph = DataFlow(mapping)

    print(f"Streaming 8206HR to {args.output} (preamp_gain={args.preamp_gain})")
    if args.duration is not None:
        print(f"Duration: {args.duration} s")
        flowgraph.collect_for_seconds(args.duration)
    else:
        print("Running until Ctrl+C.")
        with flowgraph:
            try:
                while True:
                    import time
                    time.sleep(1)
            except KeyboardInterrupt:
                pass  # __exit__ will call stop_collection()
    print("Done.")


if __name__ == "__main__":
    main()
