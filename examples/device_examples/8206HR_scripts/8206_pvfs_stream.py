"""
Stream 8206HR data to a PVFS file using the Morelia data collection pipeline.

Supports D2XX direct USB, COM port (Windows), and tty (Linux) connections. By default uses D2XX.
For D2XX, assumes the 8206HR is the only connected device, or use --device to pick by index/serial.
Output is compatible with the standard Sirenia data format (experiment.db3 + indexed channels).

Usage:
  python 8206_pvfs_stream.py [--output OUTPUT.pvfs] [--duration SECONDS] [--com-port [PORT]] [--device INDEX]
  (default: output_8206.pvfs, run until Space/Enter; default: D2XX, default port: COM9 on Windows)
  When multiple D2XX devices are present and --device is omitted, you will be prompted to choose.

Examples:
  # Use D2XX device (default)
  python 8206_pvfs_stream.py
  
  # Use COM port COM9 (Windows, blank --com-port defaults to COM9)
  python 8206_pvfs_stream.py --com-port
  
  # Use specific COM port (Windows)
  python 8206_pvfs_stream.py --com-port COM3
  
  # Use tty device (Linux)
  python 8206_pvfs_stream.py --com-port /dev/ttyUSB0
  
  # Use D2XX device by index
  python 8206_pvfs_stream.py --device 1

Requires: 8206HR connected via USB. For D2XX: drivers and ftd2xx (Windows) or pylibftdi (Linux/Mac).
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


def wait_for_stop_key():
    """Block until the user presses Space or Enter. Allows clean stop without SIGINT to worker."""
    if sys.platform == "win32":
        try:
            import msvcrt
            while True:
                ch = msvcrt.getch()
                if ch in (b' ', b'\r', b'\n'):
                    return
        except Exception:
            input("Press Enter to stop.")
    else:
        try:
            import termios
            import tty
            if not sys.stdin.isatty():
                input("Press Enter to stop.")
                return
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                try:
                    while True:
                        ch = sys.stdin.read(1)
                        if ch in (' ', '\r', '\n'):
                            return
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
            except Exception:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
                input("Press Enter to stop.")
        except ImportError:
            input("Press Enter to stop.")


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
    parser = argparse.ArgumentParser(description="Stream 8206HR data to a PVFS file (COM port or D2XX)")
    parser.add_argument(
        "--output", "-o",
        default="output_8206.pvfs",
        help="Output PVFS file path (default: output_8206.pvfs)",
    )
    parser.add_argument(
        "--com-port", "-c",
        nargs='?',
        const="COM9",
        default=None,
        help="Serial port to use. Windows: COM9, COM3, etc. Linux: /dev/ttyUSB0, /dev/ttyACM0, etc. "
             "If flag is provided without value, defaults to COM9 (Windows). If flag is not provided, uses D2XX.",
    )
    parser.add_argument(
        "--device", "-p",
        default=None,
        metavar="INDEX",
        help="D2XX device index 0,1,... (default: 0). If omitted and multiple devices exist, you will be prompted to choose.",
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
        help="Baud rate for communication (default: 115200)",
    )
    args = parser.parse_args()

    # Determine connection type: COM port or D2XX
    # args.com_port is None if flag not provided, "COM9" if flag provided without value, or the provided value
    use_d2xx = False
    port = None
    
    if args.com_port is not None:
        # Serial port was specified (either explicitly or as default COM9)
        # Handles both Windows COM ports (COM9, COM3) and Linux tty devices (/dev/ttyUSB0, /dev/ttyACM0)
        port = args.com_port.strip() if args.com_port.strip() else "COM9"
        print(f"Using serial port: {port}")
    else:
        # Use D2XX - list devices and use serial as port so queue manager gets a string key
        use_d2xx = True
        devices = list_d2xx_devices()
        if not devices:
            print("No D2XX devices found or D2XX not available.", file=sys.stderr)
            print("Install ftd2xx (Windows) or pylibftdi (Linux/Mac) and ensure 8206HR is connected.", file=sys.stderr)
            print("Alternatively, specify a COM port with --com-port COM9", file=sys.stderr)
            sys.exit(1)

        if len(devices) > 1 and args.device is None:
            prompt = f"Select device index (0-{len(devices) - 1}) [0]: "
            try:
                choice = input(prompt).strip() or "0"
            except (EOFError, KeyboardInterrupt):
                print("Aborted.", file=sys.stderr)
                sys.exit(1)
            args.device = choice
        try:
            idx = int(args.device) if args.device is not None and str(args.device).strip().isdigit() else 0
        except (TypeError, ValueError):
            idx = 0
        if idx < 0 or idx >= len(devices):
            print(f"Device index {idx} out of range (0..{len(devices)-1}).", file=sys.stderr)
            sys.exit(1)

        device_serial = devices[idx]["serial"]
        if isinstance(device_serial, bytes):
            device_serial = device_serial.decode("utf-8")
        # Use serial if available, otherwise use index-based identifier for unique port
        # Empty serials would all hash to the same port, causing conflicts
        if device_serial and device_serial.strip():
            port = device_serial  # Use serial so queue server registers get_write_queue_<serial>
        else:
            # Fallback to index-based identifier when serial is empty
            port = f"D2XX_{idx}"
        print(f"Using D2XX device index {idx}: {device_serial if device_serial else '(no serial, using index)'}")

    # Create the device
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

    # Verify device type by sending TYPE command (should return 0x30/48 for 8206HR)
    # For D2XX devices, we need to open the port temporarily to verify
    # For COM port devices, the port should already be open
    print("Verifying device type...", flush=True)
    port_was_open = pod._port is not None
    try:
        # Open port if it's not already open (needed for D2XX)
        if not port_was_open:
            pod.open_port()
        
        type_response = pod.write_read('TYPE', timeout_sec=5)
        device_type = type_response.payload[0] if type_response.payload else None
        
        # 8206HR device type is 0x30 (48 in decimal)
        if device_type != 48:
            print(f"Error: Wrong device type detected. Expected 8206HR (type 48), got type {device_type}.", file=sys.stderr)
            print(f"       This device may not be an 8206HR or may have a different command set.", file=sys.stderr)
            if not port_was_open:
                pod.close_port()
            try:
                pod.cleanup()
            except Exception:
                pass
            sys.exit(1)
        
        print(f"Device verified as 8206HR (type {device_type})", flush=True)
        
        # Close port if we opened it (for D2XX, DataFlow will reopen it in worker process)
        # For COM port, keep it open as DataFlow will use it
        if not port_was_open and use_d2xx:
            pod.close_port()
            
    except TimeoutError as e:
        print(f"Error: Device did not respond to TYPE command within timeout.", file=sys.stderr)
        print(f"       The device may not be an 8206HR or may not be responding.", file=sys.stderr)
        print(f"       Check that the device is connected and the port is correct.", file=sys.stderr)
        if not port_was_open and pod._port is not None:
            pod.close_port()
        try:
            pod.cleanup()
        except Exception:
            pass
        sys.exit(1)
    except Exception as e:
        print(f"Error: Command error while verifying device: {e}", file=sys.stderr)
        print(f"       The device may not be an 8206HR or may have a different command set.", file=sys.stderr)
        print(f"       Check that the device is connected and the port is correct.", file=sys.stderr)
        if not port_was_open and pod._port is not None:
            pod.close_port()
        try:
            pod.cleanup()
        except Exception:
            pass
        sys.exit(1)

    pvfs_sink = PvfsSink(args.output, pod)
    mapping = [(pod, [pvfs_sink])]
    flowgraph = DataFlow(mapping)

    print(f"Streaming 8206HR to {args.output} (preamp_gain={args.preamp_gain})")
    try:
        if args.duration is not None:
            print(f"Duration: {args.duration} s")
            flowgraph.collect_for_seconds(args.duration)
        else:
            print("Press Space or Enter to stop.")
            with flowgraph:
                wait_for_stop_key()
    finally:
        # Ensure cleanup happens even if there's an error
        try:
            pod.cleanup()
        except Exception:
            pass  # Ignore cleanup errors
    print("Done.")


if __name__ == "__main__":
    main()
