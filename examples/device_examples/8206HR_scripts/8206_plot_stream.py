"""
Stream 8206HR data to a live EEG-style plot using Morelia's PlotSink and PlotDisplay.

Supports D2XX direct USB, COM port (Windows), and tty (Linux) connections.
One or more 8206HR devices can be streamed; each device's channels are added
to the plot in traditional EEG layout (stacked traces, time on X).
Plotting is rate-limited so that up to ~10,000 samples/sec per channel can be
handled without overwhelming the UI.

Usage:
  python 8206_plot_stream.py [--span SECONDS] [--com-port [PORT]] [--device INDEX]
  (default: D2XX first device, --span 60; use --com-port for serial)

Requires optional dependencies: pip install pyqtgraph PyQt5
"""

from pathlib import Path
import sys
import multiprocessing as mp

_examples_dir = Path(__file__).resolve().parent
_device_examples = _examples_dir.parent
_examples_root = _device_examples.parent
_project_root = _examples_root.parent
_src = _project_root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from Morelia.Devices import Pod8206HR
from Morelia.Stream.sink import PlotSink, PlotDisplay
from Morelia.Stream.data_flow import DataFlow


def list_d2xx_devices():
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
    parser = argparse.ArgumentParser(description="Stream 8206HR to live EEG-style plot")
    parser.add_argument(
        "--com-port", "-c",
        nargs="?",
        const="COM9",
        default=None,
        help="Serial port (e.g. COM9, /dev/ttyUSB0). If omitted, use D2XX.",
    )
    parser.add_argument(
        "--device", "-p",
        default=0,
        help="D2XX device index when using D2XX (default: 0)",
    )
    parser.add_argument(
        "--preamp-gain",
        type=int,
        default=100,
        choices=[10, 100],
        help="Preamp gain (default: 100)",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=115200,
        help="Baud rate (default: 115200)",
    )
    parser.add_argument(
        "--span",
        type=float,
        default=60,
        metavar="SECONDS",
        help="Time span to show before scroll in seconds (default: 60)",
    )
    args = parser.parse_args()

    use_d2xx = False
    port = None
    if args.com_port is not None:
        port = (args.com_port or "COM9").strip() or "COM9"
        print(f"Using serial port: {port}")
    else:
        use_d2xx = True
        devices = list_d2xx_devices()
        if not devices:
            print("No D2XX devices found. Use --com-port COM9 for serial.", file=sys.stderr)
            sys.exit(1)
        idx = int(args.device) if str(args.device).strip().isdigit() else 0
        if idx < 0 or idx >= len(devices):
            print(f"Device index {idx} out of range.", file=sys.stderr)
            sys.exit(1)
        device_serial = devices[idx].get("serial")
        if isinstance(device_serial, bytes):
            device_serial = device_serial.decode("utf-8")
        port = device_serial if (device_serial and device_serial.strip()) else f"D2XX_{idx}"
        print(f"Using D2XX device index {idx}")

    try:
        pod = Pod8206HR(
            port=port,
            preamp_gain=args.preamp_gain,
            baudrate=args.baudrate,
            use_d2xx=use_d2xx,
        )
    except Exception as e:
        print(f"Error initializing device: {e}", file=sys.stderr)
        sys.exit(1)

    # Optional: verify device type (8206HR = type 48)
    port_was_open = pod._port is not None
    try:
        if not port_was_open:
            pod.open_port()
        type_response = pod.write_read("TYPE", timeout_sec=5)
        device_type = type_response.payload[0] if type_response.payload else None
        if device_type != 48:
            print(f"Warning: Expected 8206HR (type 48), got {device_type}. Continuing anyway.")
        if not port_was_open and use_d2xx:
            pod.close_port()
    except Exception as e:
        print(f"Warning: Could not verify device type: {e}")
        if not port_was_open and getattr(pod, "_port", None) is not None:
            pod.close_port()

    queue = mp.Queue(maxsize=2048)
    plot_sink = PlotSink(queue, pod)
    network = [(pod, [plot_sink])]
    flow = DataFlow(network)

    print("Starting stream. Close the plot window to stop.")
    flow.collect()

    try:
        display = PlotDisplay(queue, window_sec=args.span, refresh_ms=40)
        display.run()
    except RuntimeError as e:
        if "pyqtgraph" in str(e).lower() or "pyqt" in str(e).lower():
            print("Plot display requires: pip install pyqtgraph PyQt5", file=sys.stderr)
            sys.exit(1)
        raise
    finally:
        flow.stop_collection()
        try:
            pod.cleanup()
        except Exception:
            pass

    print("Done.")


if __name__ == "__main__":
    main()
