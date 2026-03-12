"""
Stream 8401HR data to a live EEG-style plot and simultaneously to a PVFS file.

Supports D2XX direct USB, COM port (Windows), and tty (Linux) connections.
One 8401HR device is streamed; the same data is fanned out to a PlotSink (live
plot) and a PvfsSink (file). The DataFlow + RxPy publish() pattern allows any
number of sinks to be added without extra bottlenecks beyond each sink's own cost.

Usage:
  python 8401_plot_and_save_stream.py [--output OUTPUT.pvfs] [--span SECONDS] [--sample-rate RATE] [--com-port [PORT]] [--device INDEX] [--duration SECONDS]
  (default: D2XX first device, --span 60, --sample-rate 1000, --output 8401_output.pvfs; use --com-port for serial)
  When multiple D2XX devices are present and --device is omitted, you will be prompted to choose.
  Allowed sample rates: 1000, 2000, 5000, 10000, 20000
  If --duration is omitted, stream until the plot window is closed. If --duration is set, record and plot for that many seconds then stop.

Requires optional dependencies: pip install ptech-morelia[plot] (for plot). pvfs_tools for PVFS output.
"""

from pathlib import Path
import sys
import multiprocessing as mp
import threading
import time

_examples_dir = Path(__file__).resolve().parent
_device_examples = _examples_dir.parent
_examples_root = _device_examples.parent
_project_root = _examples_root.parent
_src = _project_root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from Morelia.Devices import Pod8401HR, Preamp
from Morelia.packet import PrimaryChannelMode, SecondaryChannelMode
from Morelia.Stream.sink import PlotSink, PlotDisplay, PvfsSink
from Morelia.Stream.data_flow import DataFlow


def list_d2xx_devices():
    """List available D2XX devices (if D2XX support is installed)."""
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


def _build_default_8401_pod(port: str | int, use_d2xx: bool, baudrate: int) -> Pod8401HR:
    """Construct a Pod8401HR with a sensible default configuration for plotting."""
    # 4 primary EEG/EMG channels
    primary_channel_modes = (
        PrimaryChannelMode.EEG_EMG,
        PrimaryChannelMode.EEG_EMG,
        PrimaryChannelMode.EEG_EMG,
        PrimaryChannelMode.EEG_EMG,
    )

    # 6 secondary TTL/AEXT channels (mirrors test_8401hr_sample_rates defaults)
    secondary_channel_modes = (
        SecondaryChannelMode.DIGITAL,
        SecondaryChannelMode.ANALOG,
        SecondaryChannelMode.DIGITAL,
        SecondaryChannelMode.DIGITAL,
        SecondaryChannelMode.ANALOG,
        SecondaryChannelMode.DIGITAL,
    )

    # Use a common 4-channel preamp and gains that work well with PlotSink/DataPacket8401HR
    preamp = Preamp.Preamp8406_SE
    preamp_gain = (100, 100, 100, 100)
    ss_gain = (5, 5, 5, 5)

    return Pod8401HR(
        port=port,
        preamp=preamp,
        primary_channel_modes=primary_channel_modes,
        secondary_channel_modes=secondary_channel_modes,
        preamp_gain=preamp_gain,
        ss_gain=ss_gain,
        baudrate=baudrate,
        use_d2xx=use_d2xx,
    )


def _set_sample_rate(pod: Pod8401HR, sample_rate: int, use_d2xx: bool) -> None:
    """Set and verify the 8401HR sample rate, following the high-throughput test pattern."""
    port_was_open = pod._port is not None
    try:
        if not port_was_open:
            pod.open_port()

        # Ensure streaming is stopped before changing sample rate
        try:
            pod.write_packet("STREAM", 0)
            time.sleep(0.1)
            # Flush any pending packets
            while True:
                try:
                    pod.read_pod_packet(timeout_sec=0.1)
                except TimeoutError:
                    break
        except Exception as e:
            print(f"Warning: Could not ensure streaming is stopped before setting sample rate: {e}")

        # Set sample rate (write_read allows rates above default max_sample_rate if firmware supports them)
        pod.write_read("SET SAMPLE RATE", sample_rate, timeout_sec=5)

        # Verify sample rate
        try:
            rate_response = pod.write_read("GET SAMPLE RATE", timeout_sec=5)
            actual_rate = rate_response.payload[0] if rate_response.payload else None
            if actual_rate != sample_rate:
                print(
                    f"Warning: Requested sample rate {sample_rate} Hz but device reports {actual_rate}. "
                    "Continuing anyway."
                )
        except Exception as e:
            print(f"Warning: Could not verify sample rate after setting to {sample_rate} Hz: {e}")

        # Cache the sample rate for downstream components (e.g., timestamping)
        pod._sample_rate = (sample_rate,)
    except Exception as e:
        print(f"Warning: Could not set sample rate to {sample_rate} Hz: {e}")
    finally:
        # Mirror the behavior used elsewhere: close D2XX ports we opened, leave others alone
        if not port_was_open and use_d2xx and getattr(pod, "_port", None) is not None:
            try:
                pod.close_port()
            except Exception:
                pass


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Stream 8401HR to live EEG-style plot and PVFS file"
    )
    parser.add_argument(
        "--com-port",
        "-c",
        nargs="?",
        const="COM9",
        default=None,
        help="Serial port (e.g. COM9, /dev/ttyUSB0). If omitted, use D2XX when available.",
    )
    parser.add_argument(
        "--device",
        "-p",
        default=None,
        metavar="INDEX",
        help="D2XX device index when using D2XX (default: 0). If omitted and multiple devices exist, you will be prompted to choose.",
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
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=1000,
        choices=[1000, 2000, 5000, 10000, 20000],
        metavar="RATE",
        help="Sample rate in Hz (allowed: 1000, 2000, 5000, 10000, 20000; default: 1000)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="8401_output.pvfs",
        help="Output PVFS file path (default: 8401_output.pvfs)",
    )
    parser.add_argument(
        "--duration",
        "-d",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Record and plot for SECONDS then stop. If omitted, stream until plot window is closed.",
    )
    args = parser.parse_args()

    # Determine connection type and port
    use_d2xx = False
    port = None
    if args.com_port is not None:
        port = (args.com_port or "COM9").strip() or "COM9"
        print(f"Using serial port: {port}")
    else:
        try:
            devices = list_d2xx_devices()
            if devices:
                use_d2xx = True
                if len(devices) > 1 and args.device is None:
                    prompt = f"Select device index (0-{len(devices) - 1}) [0]: "
                    try:
                        choice = input(prompt).strip() or "0"
                    except (EOFError, KeyboardInterrupt):
                        print("Aborted.", file=sys.stderr)
                        sys.exit(1)
                    args.device = choice
                idx = int(args.device) if args.device is not None and str(args.device).strip().isdigit() else 0
                if idx < 0 or idx >= len(devices):
                    print(f"D2XX device index {idx} out of range (0-{len(devices) - 1}).", file=sys.stderr)
                    sys.exit(1)
                device_serial = devices[idx].get("serial")
                if isinstance(device_serial, bytes):
                    device_serial = device_serial.decode("utf-8")
                port = device_serial if (device_serial and device_serial.strip()) else f"D2XX_{idx}"
                print(f"Using D2XX device: {port}")
            else:
                print("No D2XX devices found; cannot open 8401HR when VCP is disabled.", file=sys.stderr)
                sys.exit(1)
        except ImportError:
            print("D2XX not available (pip install ptech-morelia[d2xx]); cannot open 8401HR when VCP is disabled.", file=sys.stderr)
            sys.exit(1)

    # Initialize 8401HR device
    try:
        pod = _build_default_8401_pod(port=port, use_d2xx=use_d2xx, baudrate=args.baudrate)
    except Exception as e:
        print(f"Error initializing 8401HR device: {e}", file=sys.stderr)
        sys.exit(1)

    # Configure sample rate on the device for the streaming worker and timestamping
    _set_sample_rate(pod, args.sample_rate, use_d2xx=use_d2xx)

    # Shared queue for plot sink; PlotDisplay (main process) consumes from it.
    queue = mp.Queue(maxsize=2048)
    plot_sink = PlotSink(queue, pod)
    pvfs_sink = PvfsSink(args.output, pod, observe_on_scheduler="thread_pool")

    # Extensible sink list: DataFlow + RxPy publish() fan out the same stream to every
    # sink; each sink's flush(timestamp, packet) is called once per sample. Throughput
    # is limited only by the slowest sink and the device—no extra queues or copies.
    # To add more sinks (e.g. UDPSink, BufferSink, EDFSink), instantiate them with the
    # same pod and append to this list.
    sinks = [plot_sink, pvfs_sink]

    network = [(pod, sinks)]
    flow = DataFlow(network)

    # When duration is set, stop collection and close the plot after that many seconds.
    timer = None
    if args.duration is not None:
        from pyqtgraph.Qt import QtWidgets

        def stop_and_quit() -> None:
            flow.stop_collection()
            app = QtWidgets.QApplication.instance()
            if app is not None:
                app.quit()

        timer = threading.Timer(args.duration, stop_and_quit)
        timer.daemon = True
        timer.start()
        print(f"Recording and plotting 8401HR at {args.sample_rate} Hz to {args.output} for {args.duration} s.")
    else:
        print(f"Starting 8401HR stream at {args.sample_rate} Hz to plot and {args.output}. Close the plot window to stop.")

    flow.collect()

    try:
        display = PlotDisplay(queue, window_sec=args.span, refresh_ms=40)
        display.run()
    except RuntimeError as e:
        if "pyqtgraph" in str(e).lower() or "pyqt" in str(e).lower():
            print("Plot display requires: pip install ptech-morelia[plot]", file=sys.stderr)
            sys.exit(1)
        raise
    finally:
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass
        flow.stop_collection()
        try:
            pod.cleanup()
        except Exception:
            pass

    print("Done.")


if __name__ == "__main__":
    main()
