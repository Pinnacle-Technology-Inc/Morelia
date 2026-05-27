"""
Stream 8401HR data to a live EEG-style plot using Morelia's PlotSink and PlotDisplay.

Supports D2XX direct USB, COM port (Windows), and tty (Linux) connections.
One 8401HR device can be streamed; the device's channels are added
to the plot in traditional EEG-style layout (stacked traces, time on X).
Plotting is rate-limited so that high sample rates (up to 20,000 sps)
can be handled without overwhelming the UI.

Usage:
  python 8401_plot_stream.py [--span SECONDS] [--sample-rate RATE] [--com-port [PORT]] [--device INDEX]
  python 8401_plot_stream.py --preamp 8406-SE3   # configure device for a specific preamp model
  python 8401_plot_stream.py --save-config [FILE]  # save current device config to TOML, then stream
  python 8401_plot_stream.py --load-config [FILE]  # load config from TOML, apply, then stream

  (default: D2XX first device, --span 60, --sample-rate 1000; use --com-port for serial)
  When multiple D2XX devices are present and --device is omitted, you will be prompted to choose.
  Allowed sample rates: 1000, 2000, 5000, 10000, 20000
  --preamp applies a known preamp configuration (dc_mode, highpass, lowpass, bias, ss_config, inversion).
  Config file defaults to config.toml when --save-config or --load-config is used without a filename.
  CLI qualifiers (e.g. --sample-rate, --preamp) override values from the config file.
  Specifying both --save-config and --load-config cancels out (neither is applied).

Requires optional dependencies: pip install ptech-morelia[plot]
"""

from pathlib import Path
import os
import sys
import multiprocessing as mp
import time
import toml

_examples_dir = Path(__file__).resolve().parent
_device_examples = _examples_dir.parent
_examples_root = _device_examples.parent
_project_root = _examples_root.parent
_src = _project_root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from Morelia.Devices import Pod8401HR, Preamp
from Morelia.packet import PrimaryChannelMode, SecondaryChannelMode
from Morelia.Stream.sink import PlotSink, PlotDisplay
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


def _save_device_config(pod: Pod8401HR, filepath: str, use_d2xx: bool) -> None:
    """Read the device's current configuration and write it to a TOML file.

    Opens the port temporarily if it is not already open (e.g. D2XX deferred
    open pattern).
    """
    filepath = os.path.abspath(filepath)
    folder = os.path.dirname(filepath)
    basename = os.path.basename(filepath)

    port_was_open = pod._port is not None
    try:
        if not port_was_open:
            pod.open_port()

        # Stop streaming in case device is in an active state
        try:
            pod.write_packet("STREAM", 0)
            time.sleep(0.1)
            while True:
                try:
                    pod.read_pod_packet(timeout_sec=0.1)
                except TimeoutError:
                    break
        except Exception:
            pass

        pod.get_config(folder, basename)
    finally:
        if not port_was_open and use_d2xx and getattr(pod, "_port", None) is not None:
            try:
                pod.close_port()
            except Exception:
                pass


def _load_and_apply_config(
    pod: Pod8401HR,
    filepath: str,
    use_d2xx: bool,
    cli_overrides: dict | None = None,
) -> int | None:
    """Load a TOML config file and apply it to the device.

    *cli_overrides* is a dict of property names whose values were explicitly
    provided on the command line.  Those keys are removed from the config
    before it is applied so that the CLI value takes precedence.

    Returns the ``sample_rate`` found in the config (or ``None`` if absent),
    so the caller can decide whether to use it or a CLI / default value.
    """
    filepath = os.path.abspath(filepath)
    if not os.path.exists(filepath):
        print(f"Config file not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    config = toml.load(filepath)

    # Extract sample_rate from config before applying (handled separately
    # by _set_sample_rate which also stops streaming and verifies).
    config_sample_rate = None
    sr_section = config.get("sample_rate")
    if isinstance(sr_section, dict):
        config_sample_rate = sr_section.pop("sample_rate", None)
        if not sr_section:
            config.pop("sample_rate", None)
    elif isinstance(sr_section, (int, float)):
        config_sample_rate = int(sr_section)
        config.pop("sample_rate", None)

    # Strip any remaining keys that the CLI explicitly overrides
    if cli_overrides:
        for key in cli_overrides:
            config.pop(key, None)
            for section in list(config.values()):
                if isinstance(section, dict):
                    section.pop(key, None)

    # Apply the remaining config to the device (needs an open port)
    port_was_open = pod._port is not None
    try:
        if not port_was_open:
            pod.open_port()

        # Stop streaming in case device is in an active state
        try:
            pod.write_packet("STREAM", 0)
            time.sleep(0.1)
            while True:
                try:
                    pod.read_pod_packet(timeout_sec=0.1)
                except TimeoutError:
                    break
        except Exception:
            pass

        pod.apply_config(config)
    finally:
        if not port_was_open and use_d2xx and getattr(pod, "_port", None) is not None:
            try:
                pod.close_port()
            except Exception:
                pass

    return config_sample_rate


def _apply_preamp(pod: Pod8401HR, model: str, use_d2xx: bool) -> None:
    """Apply a preamp configuration by model number.

    Opens the port temporarily if needed and stops streaming before
    sending hardware commands.
    """
    port_was_open = pod._port is not None
    try:
        if not port_was_open:
            pod.open_port()

        try:
            pod.write_packet("STREAM", 0)
            time.sleep(0.1)
            while True:
                try:
                    pod.read_pod_packet(timeout_sec=0.1)
                except TimeoutError:
                    break
        except Exception:
            pass

        pod.apply_preamp_config(model)
    finally:
        if not port_was_open and use_d2xx and getattr(pod, "_port", None) is not None:
            try:
                pod.close_port()
            except Exception:
                pass


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Stream 8401HR to live EEG-style plot")
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
        default=None,
        choices=[1000, 2000, 5000, 10000, 20000],
        metavar="RATE",
        help="Sample rate in Hz (allowed: 1000, 2000, 5000, 10000, 20000; default: 1000). Overrides config file value.",
    )
    parser.add_argument(
        "--preamp",
        default=None,
        metavar="MODEL",
        help="Preamp model number (e.g. 8406-SE3). Configures dc_mode, highpass, lowpass, bias, ss_config, and channel inversion. Overrides preamp_model from config file.",
    )
    parser.add_argument(
        "--save-config",
        nargs="?",
        const="config.toml",
        default=None,
        metavar="FILE",
        help="Save the connected device's current configuration to a TOML file, then continue streaming (default: config.toml).",
    )
    parser.add_argument(
        "--load-config",
        nargs="?",
        const="config.toml",
        default=None,
        metavar="FILE",
        help="Load device configuration from a TOML file before streaming (default: config.toml). CLI qualifiers override config values.",
    )
    args = parser.parse_args()

    # Determine connection type and port
    use_d2xx = False
    port = None
    if args.com_port is not None:
        port = (args.com_port or "COM9").strip() or "COM9"
        print(f"Using serial port: {port}")
    else:
        # Match the D2XX discovery logic used in tests/test_8401hr_sample_rates.py
        try:
            devices = list_d2xx_devices()
            if devices:
                use_d2xx = True
                # When multiple devices and no --device given, prompt user to choose
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

    # When both --save-config and --load-config are specified, saving the
    # current config and immediately reloading it is a no-op, so skip both.
    config_sample_rate = None
    if args.save_config is not None and args.load_config is not None:
        print("Both --save-config and --load-config specified; skipping both.")
    else:
        # --save-config: save current device config to TOML, then continue streaming
        if args.save_config is not None:
            _save_device_config(pod, args.save_config, use_d2xx)

        # --load-config: load config from TOML and apply to device.
        # Build a dict of properties explicitly provided on the CLI so they
        # are not overwritten by the config file.
        if args.load_config is not None:
            cli_overrides = {}
            if args.sample_rate is not None:
                cli_overrides["sample_rate"] = args.sample_rate
            if args.preamp is not None:
                cli_overrides["preamp_model"] = args.preamp
            config_sample_rate = _load_and_apply_config(
                pod, args.load_config, use_d2xx, cli_overrides=cli_overrides
            )

    # Apply preamp configuration (CLI --preamp takes priority; if not
    # provided, the TOML config may have already applied it above).
    if args.preamp is not None:
        _apply_preamp(pod, args.preamp, use_d2xx)

    # Resolve final sample rate: CLI > config file > default (1000)
    sample_rate = args.sample_rate or config_sample_rate or 1000

    # Configure sample rate on the device for the streaming worker and timestamping
    _set_sample_rate(pod, sample_rate, use_d2xx=use_d2xx)

    queue = mp.Queue(maxsize=2048)
    plot_sink = PlotSink(queue, pod)
    network = [(pod, [plot_sink])]
    flow = DataFlow(network)

    print(f"Starting 8401HR stream at {sample_rate} Hz. Close the plot window to stop.")
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
        flow.stop_collection()
        try:
            pod.cleanup()
        except Exception:
            pass

    print("Done.")


if __name__ == "__main__":
    main()

