"""
Stream 8206HR data over UDP to a configurable host/port.

Supports D2XX direct USB, COM port (Windows), and tty (Linux) connections. By default uses D2XX.
Each sample is sent as one UDP datagram (binary: 8-byte timestamp + 3 floats for ch0–ch2).
Use a listener on the destination host/port to verify the stream; this script only sends.

Usage:
  python 8206_udp_stream.py [--udp-host HOST] [--udp-port PORT] [--duration SECONDS] [--com-port [PORT]] [--device INDEX]
  (default: 127.0.0.1:9000, run until Ctrl+C; use --com-port for serial, otherwise D2XX)

Examples:
  # Stream to localhost:9000 (default)
  python 8206_udp_stream.py

  # Stream to another host and port
  python 8206_udp_stream.py --udp-host 192.168.1.10 --udp-port 12345

  # Use COM port (Windows)
  python 8206_udp_stream.py --com-port COM9

  # Stream for 10 seconds
  python 8206_udp_stream.py --duration 10

Requires: 8206HR connected via USB. For D2XX: drivers and ftd2xx (Windows) or pylibftdi (Linux/Mac).
"""

from pathlib import Path
import sys

_examples_dir = Path(__file__).resolve().parent
_device_examples = _examples_dir.parent
_examples_root = _device_examples.parent
_project_root = _examples_root.parent
_src = _project_root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from Morelia.Devices import Pod8206HR
from Morelia.Stream.sink import UDPSink
from Morelia.Stream.data_flow import DataFlow


def list_d2xx_devices():
    """List all available FTDI D2XX devices."""
    try:
        from Morelia.Devices.SerialPorts.d2xx_helpers import list_d2xx_devices
        devices = list_d2xx_devices()
        print("Available D2XX devices:")
        for dev in devices:
            print(f"  Index {dev['index']}: {dev['description']} (Serial: {dev['serial']})")
        return devices
    except ImportError:
        print("D2XX support not available. Install with: pip install ptech-morelia[d2xx]")
        return []


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Stream 8206HR data over UDP (COM port or D2XX)"
    )
    parser.add_argument(
        "--udp-host",
        default="127.0.0.1",
        metavar="HOST",
        help="UDP destination host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--udp-port",
        "-u",
        type=int,
        default=9000,
        metavar="PORT",
        help="UDP destination port (default: 9000)",
    )
    parser.add_argument(
        "--com-port", "-c",
        nargs="?",
        const="COM9",
        default=None,
        help="Serial port. Windows: COM9, COM3, etc. Linux: /dev/ttyUSB0. "
             "If omitted, use D2XX. If given with no value, default COM9.",
    )
    parser.add_argument(
        "--device", "-p",
        default=0,
        help="D2XX device index 0,1,... when using D2XX (default: 0)",
    )
    parser.add_argument(
        "--duration", "-d",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Stream for SECONDS then stop (default: until Ctrl+C)",
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
        help="Baud rate (default: 115200)",
    )
    args = parser.parse_args()

    use_d2xx = False
    port = None

    if args.com_port is not None:
        port = (args.com_port or "COM9").strip() or "COM9"
        print(f"Using serial port: {port}")
    else:
        devices = list_d2xx_devices()
        if not devices:
            print("No D2XX devices found or D2XX not available (pip install ptech-morelia[d2xx]).", file=sys.stderr)
            print("Use --com-port COM9 (or /dev/ttyUSB0) for serial.", file=sys.stderr)
            sys.exit(1)
        try:
            idx = int(args.device) if str(args.device).strip().isdigit() else 0
        except (TypeError, ValueError):
            idx = 0
        if idx < 0 or idx >= len(devices):
            print(f"Device index {idx} out of range (0..{len(devices)-1}).", file=sys.stderr)
            sys.exit(1)
        use_d2xx = True
        device_serial = devices[idx]["serial"]
        if isinstance(device_serial, bytes):
            device_serial = device_serial.decode("utf-8")
        port = device_serial if (device_serial and device_serial.strip()) else f"D2XX_{idx}"
        print(f"Using D2XX device index {idx}: {device_serial or '(no serial)'}")

    try:
        pod = Pod8206HR(
            port=port,
            preamp_gain=args.preamp_gain,
            baudrate=args.baudrate,
            use_d2xx=use_d2xx,
        )
    except Exception as e:
        print(f"Error: Failed to initialize device: {e}", file=sys.stderr)
        sys.exit(1)

    print("Verifying device type...", flush=True)
    port_was_open = pod._port is not None
    try:
        if not port_was_open:
            pod.open_port()
        type_response = pod.write_read("TYPE", timeout_sec=5)
        device_type = type_response.payload[0] if type_response.payload else None
        if device_type != 48:
            print(f"Error: Expected 8206HR (type 48), got type {device_type}.", file=sys.stderr)
            if not port_was_open:
                pod.close_port()
            try:
                pod.cleanup()
            except Exception:
                pass
            sys.exit(1)
        print("Device verified as 8206HR (type 48)", flush=True)
        if not port_was_open and use_d2xx:
            pod.close_port()
    except TimeoutError:
        print("Error: Device did not respond to TYPE command.", file=sys.stderr)
        if not port_was_open and getattr(pod, "_port", None) is not None:
            pod.close_port()
        try:
            pod.cleanup()
        except Exception:
            pass
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if not port_was_open and getattr(pod, "_port", None) is not None:
            pod.close_port()
        try:
            pod.cleanup()
        except Exception:
            pass
        sys.exit(1)

    udp_sink = UDPSink(
        port=args.udp_port,
        pod=pod,
        host=args.udp_host,
    )
    network = [(pod, [udp_sink])]
    flow = DataFlow(network)

    print(f"Streaming 8206HR to UDP {args.udp_host}:{args.udp_port} (preamp_gain={args.preamp_gain})")
    print("Start a listener on that address to verify. Ctrl+C to stop.")
    try:
        if args.duration is not None:
            flow.collect_for_seconds(args.duration)
        else:
            with flow:
                try:
                    while True:
                        import time
                        time.sleep(1)
                except KeyboardInterrupt:
                    pass
    finally:
        try:
            pod.cleanup()
        except Exception:
            pass
    print("Done.")


if __name__ == "__main__":
    main()
