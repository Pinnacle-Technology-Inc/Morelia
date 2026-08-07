"""Watchdog process entrypoint — ``python -m app.watchdog_process``.

Loads an immutable manifest from ``--manifest`` and initializes with
``runtime_id``, ``watchdog_id``, an optional token, the control plane's
ingest URL, and an outbox path, then owns Morelia, DataFlow, DataFlow stream
workers, sinks, the SQLite outbox, and direct telemetry flushing to the
control plane (see ``app.watchdog_process.process.WatchdogProcess``).

Prints:

    READY

to stdout once the driver has started, mirroring runtime_host's stdout
handshake convention (see ``app/runtime_host/__main__.py``) so a supervising
process can detect readiness deterministically without polling. Unlike
runtime_host there is no port to hand back — the watchdog process reports
directly to the control plane rather than serving a command socket.

Exit codes: 0 on a clean SIGINT/SIGTERM shutdown, 1 if a fatal ingest
response (stale/unauthorized) stopped the process on its own.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from collections.abc import Callable

from app.config import get_config
from app.logging_config import configure_logging
from app.runtime_child.driver import RuntimeControlDriver
from app.runtime_host.manifest import Manifest
from app.watchdog_process.control import WatchdogControlServer
from app.watchdog_process.hardware_lease import HardwareLeaseSet
from app.watchdog_process.outbox import WatchdogOutbox, default_outbox_path
from app.watchdog_process.process import WatchdogIdentity, WatchdogProcess
from app.watchdog_process.process_tree import install_process_tree_guard
from app.watchdog_process.telemetry_client import TelemetryClient


def _build_driver(
    manifest: Manifest,
    *,
    driver_name: str,
    on_report,
    sink_delivery_outbox_factory=None,
) -> RuntimeControlDriver:
    if driver_name == "morelia":
        from app.runtime_child.morelia import MoreliaRuntime

        config = get_config()
        return MoreliaRuntime(
            manifest=manifest,
            on_report=on_report,
            failure_threshold=config.WATCHDOG_FAILURE_THRESHOLD,
            max_heartbeat_age_sec=config.WATCHDOG_MAX_HEARTBEAT_AGE_SECONDS,
            first_packet_timeout_sec=config.WATCHDOG_FIRST_PACKET_TIMEOUT_SECONDS,
            report_interval_sec=config.WATCHDOG_REPORT_INTERVAL_SECONDS,
            stream_interval_sec=config.WATCHDOG_STREAM_INTERVAL_SECONDS,
            timeout_sec=config.WATCHDOG_OPERATION_TIMEOUT_SECONDS,
            shutdown_timeout_sec=config.WATCHDOG_DATAFLOW_STOP_TIMEOUT_SECONDS,
            sink_delivery_outbox_factory=sink_delivery_outbox_factory,
        )
    raise ValueError(f"unknown runtime driver: {driver_name!r}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Watchdog Process")
    parser.add_argument("--manifest", required=True, help="Path to manifest JSON file")
    parser.add_argument("--runtime-id", required=True, help="Owning runtime host's runtime_id")
    parser.add_argument(
        "--watchdog-id", required=True, help="This watchdog-process instance's identity"
    )
    parser.add_argument(
        "--ingest-url",
        required=True,
        help="Control plane base URL for direct telemetry ingest",
    )
    parser.add_argument(
        "--ingest-token",
        default=None,
        help="Token sent as X-Agent-Token to the ingest endpoint",
    )
    parser.add_argument(
        "--outbox-path",
        default=None,
        help="Explicit SQLite outbox file path (default: derived from --outbox-dir + watchdog-id)",
    )
    parser.add_argument(
        "--outbox-dir",
        default=None,
        help="Directory to derive the outbox path under when --outbox-path is omitted "
        "(default: WATCHDOG_OUTBOX_DIR)",
    )
    parser.add_argument(
        "--hardware-lock-dir",
        default=None,
        help="Directory containing OS-locked per-device lease files",
    )
    parser.add_argument(
        "--control-token",
        default=None,
        help="Secret used to authenticate the loopback watchdog recovery channel",
    )
    parser.add_argument(
        "--driver",
        choices=("morelia",),
        default="morelia",
        help="Runtime driver to run (default: morelia)",
    )
    return parser


def build_process(args: argparse.Namespace) -> WatchdogProcess:
    """Wire manifest + identity + outbox + telemetry client into one WatchdogProcess.

    Split out from ``main()`` so tests can construct (and inspect) a process
    from parsed args without running the blocking signal loop below.
    """
    import functools

    from app.runtime_child.morelia import open_sink_delivery_outbox
    from app.watchdog_process.sink_delivery_outbox import default_sink_delivery_outbox_path

    with open(args.manifest, encoding="utf-8") as fh:
        manifest = Manifest.from_dict(json.load(fh))

    outbox_path = args.outbox_path or default_outbox_path(
        args.outbox_dir or get_config().WATCHDOG_OUTBOX_DIR, args.watchdog_id
    )
    outbox = WatchdogOutbox(outbox_path)
    config = get_config()
    client = TelemetryClient(
        base_url=args.ingest_url,
        token=args.ingest_token,
        timeout_seconds=config.WATCHDOG_TELEMETRY_TIMEOUT_SECONDS,
    )
    identity = WatchdogIdentity(
        runtime_id=args.runtime_id,
        watchdog_id=args.watchdog_id,
    )
    # One stable per-dataflow SinkDeliveryOutbox (packet 19/26), named by
    # watchdog_id and kept SEPARATE from the telemetry WatchdogOutbox above. It is
    # threaded as a PICKLABLE, path-based FACTORY (never a live SQLite handle,
    # which cannot cross the DataFlow worker boundary): the selected Influx/Quest
    # workers open their own handle; a file-only/CSV-only manifest opens none.
    sink_delivery_outbox_path = default_sink_delivery_outbox_path(
        config.SINK_DELIVERY_OUTBOX_DIR, manifest.dataflow_id
    )
    sink_delivery_outbox_factory = functools.partial(
        open_sink_delivery_outbox, str(sink_delivery_outbox_path)
    )
    return WatchdogProcess(
        manifest=manifest,
        identity=identity,
        outbox=outbox,
        telemetry_client=client,
        build_driver=lambda **kwargs: _build_driver(
            driver_name=args.driver,
            sink_delivery_outbox_factory=sink_delivery_outbox_factory,
            **kwargs,
        ),
        stale_grace_attempts=config.WATCHDOG_STALE_GRACE_ATTEMPTS,
    )


def main(
    argv: list[str] | None = None,
    *,
    process_factory: Callable[[argparse.Namespace], WatchdogProcess] = build_process,
    process_tree_guard_factory: Callable[[], object | None] = install_process_tree_guard,
    poll_interval_seconds: float | None = None,
) -> int:
    args = build_arg_parser().parse_args(argv)
    poll_interval_seconds = (
        get_config().WATCHDOG_PROCESS_LOOP_INTERVAL_SECONDS
        if poll_interval_seconds is None
        else poll_interval_seconds
    )

    # stderr, not stdout: stdout carries the READY handshake (see module
    # docstring) — log lines there would corrupt it.
    configure_logging(get_config(), stream=sys.stderr)

    # Install containment before Morelia constructs any stream workers or
    # queue servers. This reference keeps the Job Object handle open until the
    # watchdog process itself exits.
    _process_tree_guard = process_tree_guard_factory()
    process = process_factory(args)
    hardware_leases = HardwareLeaseSet(
        process.manifest,
        directory=args.hardware_lock_dir or get_config().WATCHDOG_HARDWARE_LOCK_DIR,
    )

    stop_event = threading.Event()
    control_server: WatchdogControlServer | None = None
    ready_announced = False

    def _shutdown(signum, frame):  # noqa: ARG001
        stop_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        # Selection-aware dependency preflight FIRST — before any hardware
        # ownership changes (gap SINK-13). This is the worker-boundary guard:
        # if a selected sink's optional/native dependency is missing, fail here
        # with the typed, redacted SinkDependencyMissing rather than after
        # acquiring device leases. CSV/Plot-only manifests always pass. The
        # probe opens no files/sockets and spawns nothing, so on success there
        # is nothing extra to unwind.
        from app.runtime_child.morelia import preflight_sink_dependencies

        preflight_sink_dependencies(process.manifest)
        hardware_leases.acquire()
        process.driver.preflight()
        process.driver.start()

        if args.control_token:
            control_server = WatchdogControlServer(
                process=process,
                token=args.control_token,
                hardware_lease_keys=hardware_leases.keys,
                request_stop=stop_event.set,
            )
            control_server.start()

        # Flush immediately — the parent reads this line to learn we are up.
        ready = f"READY:{control_server.port}" if control_server is not None else "READY"
        print(ready, flush=True)
        ready_announced = True

        while not stop_event.wait(timeout=poll_interval_seconds):
            if process.stopped:
                break

        # Always call shutdown, even if a fatal ingest response already
        # stopped the driver — shutdown() is idempotent, and this is the one
        # path that also runs on a clean SIGINT/SIGTERM.
        process.shutdown()
    except Exception as exc:
        if not ready_announced:
            payload = {
                "error_type": str(getattr(exc, "error_type", type(exc).__name__))[:120],
                "message": str(getattr(exc, "reason", str(exc)))[:500],
                "device_id": getattr(exc, "device_id", None),
                "sink_id": getattr(exc, "sink_id", None),
            }
            print(f"ERROR:{json.dumps(payload, separators=(',', ':'))}", flush=True)
            return 1
        raise
    finally:
        try:
            if control_server is not None:
                control_server.stop()
        finally:
            try:
                process.outbox.close()
            finally:
                hardware_leases.release()

    return 1 if process.stopped else 0


if __name__ == "__main__":
    sys.exit(main())
