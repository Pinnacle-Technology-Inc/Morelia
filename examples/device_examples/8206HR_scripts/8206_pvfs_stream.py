"""
Stream 8206HR data to a PVFS file using the Morelia data collection pipeline.

This example connects to a single 8206HR device and records to a .pvfs file
compatible with the standard Sirenia data format (experiment.db3 + indexed channels).

Usage:
  python 8206_pvfs_stream.py [--output OUTPUT.pvfs] [--duration SECONDS]
  (default: output_8206.pvfs, stream until Ctrl+C or stop_collection())

Requires: 8206HR device on the given port (e.g. /dev/ttyUSB0 on Linux, COM3 on Windows).
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


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Stream 8206HR data to a PVFS file")
    parser.add_argument(
        "--output", "-o",
        default="output_8206.pvfs",
        help="Output PVFS file path (default: output_8206.pvfs)",
    )
    parser.add_argument(
        "--port", "-p",
        default="/dev/ttyUSB0",
        help="Serial port (default: /dev/ttyUSB0; use COM3 etc. on Windows)",
    )
    parser.add_argument(
        "--duration", "-d",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Record for SECONDS then stop (default: run until stop_collection)",
    )
    parser.add_argument(
        "--gain", "-g",
        type=int,
        default=10,
        choices=[10, 100],
        help="Preamplifier gain (default: 10)",
    )
    args = parser.parse_args()

    pod = Pod8206HR(args.port, args.gain)
    pvfs_sink = PvfsSink(args.output, pod)
    mapping = [(pod, [pvfs_sink])]
    flowgraph = DataFlow(mapping)

    print(f"Streaming 8206HR to {args.output} (port={args.port}, gain={args.gain})")
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
