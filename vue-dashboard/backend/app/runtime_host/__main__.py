"""Dataflow Runtime Host entrypoint — ``python -m app.runtime_host``.

Loads an immutable manifest from ``--manifest``, assembles the driver stack,
and serves the watchdog command contract on loopback.  Prints two lines to
stdout so the parent process knows it is safe to connect:

    PORT:<n>
    READY

Shutdown: SIGINT or SIGTERM sets a stop event; the main thread then calls
``host.stop()``, drives the driver to a terminal phase if it never got a
``stop`` command, and calls ``driver.close()`` before exiting.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
from contextlib import suppress
from uuid import uuid4

import structlog

from app.config import get_config
from app.logging_config import configure_logging
from app.runtime_child.driver import RuntimePhase
from app.runtime_host.lifecycle import LifecycleSafetyGate
from app.runtime_host.manifest import Manifest
from app.runtime_host.server import DataflowRuntimeHost, RuntimeHostLease
from app.runtime_host.watchdog_process_driver import WatchdogProcessDriver

DEFAULT_LEASE_TIMEOUT_SECONDS = 30 * 60

_log = structlog.get_logger(__name__)

# Phases from which WatchdogProcessDriver.stop() accepts being called. IDLE
# (never preflighted/started) and
# CLOSED (already torn down) are not in this set, so calling stop() from
# those phases would raise — nothing to gracefully stop in either case.
_STOPPABLE_PHASES = (RuntimePhase.PREFLIGHT, RuntimePhase.RUNNING)


def _prepare_driver_for_host_start(driver: WatchdogProcessDriver) -> None:
    """Establish watchdog readiness before announcing runtime-host READY.

    Make 2 different startup routes. If runtime_host is first initiated, it will have to send
    preflight command to watchdog to prepare the device (send STREAM 0 just in case hardware
    device is stuck in the previous streaming states). If runtime_host is respawned after a crash
    it might already have a watchdog running that it need to adopt.
    """
    if driver.phase is RuntimePhase.IDLE:
        driver.preflight()
        ensure_preflight_ready = getattr(driver, "ensure_preflight_ready", None)
        if ensure_preflight_ready is not None:
            ensure_preflight_ready()
        return

    if driver.phase is RuntimePhase.RUNNING:
        if not driver.watchdog_preflight_ready:
            raise RuntimeError(
                "adopted watchdog is running without preflight readiness proof"
            )
        return

    raise RuntimeError(
        "runtime host driver must be idle or adopted-running before host start; "
        f"got phase {driver.phase.value!r}"
    )


def _build_driver(
    manifest: Manifest,
    *,
    manifest_path: str,
    driver_name: str,
    on_report,
    runtime_id: str,
    ingest_url: str | None,
    ingest_token: str | None,
    outbox_dir: str | None,
    hardware_lock_dir: str | None,
    control_token: str | None,
    adopt_watchdog_id: str | None,
    adopt_watchdog_pid: int | None,
    adopt_watchdog_control_port: int | None,
) -> WatchdogProcessDriver:
    """Build runtime_host's own driver: always a ``WatchdogProcessDriver`` (packet 06).

    ``driver_name`` selects the *ultimate* hardware driver — it is forwarded
    to the watchdog process as its own ``--driver``. runtime_host itself never
    imports Morelia or any concrete driver directly; the watchdog process is
    the only process that touches hardware (packet 05's contract).
    """
    if driver_name != "morelia":
        raise ValueError(f"unknown runtime driver: {driver_name!r}")
    return WatchdogProcessDriver(
        manifest=manifest,
        manifest_path=manifest_path,
        on_report=on_report,
        runtime_id=runtime_id,
        ingest_url=ingest_url,
        ingest_token=ingest_token,
        outbox_dir=outbox_dir,
        hardware_lock_dir=hardware_lock_dir,
        control_token=control_token,
        driver_name=driver_name,
        adopt_watchdog_id=adopt_watchdog_id,
        adopt_watchdog_pid=adopt_watchdog_pid,
        adopt_watchdog_control_port=adopt_watchdog_control_port,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Dataflow Runtime Host")
    parser.add_argument("--manifest", required=True, help="Path to manifest JSON file")
    parser.add_argument("--port", type=int, default=0, help="Bind port (0 = OS picks)")
    parser.add_argument("--token", default=None, help="Per-host auth token")
    parser.add_argument("--runtime-id", default=None, help="Runtime ownership id")
    parser.add_argument(
        "--ingest-url",
        default=None,
        help="Control plane BASE url; senders append /api/v1/internal/events themselves",
    )
    parser.add_argument(
        "--ingest-token",
        default=None,
        help="Token sent as X-Agent-Token to the ingest endpoint",
    )
    parser.add_argument(
        "--outbox-dir",
        default=None,
        help="Directory to derive the spawned watchdog process's outbox path under "
        "(default: WATCHDOG_OUTBOX_DIR)",
    )
    parser.add_argument(
        "--hardware-lock-dir",
        default=None,
        help="Directory containing OS-locked per-device watchdog leases",
    )
    parser.add_argument(
        "--adopt-watchdog-id",
        default=None,
        help="Identity of a pre-existing watchdog process to adopt instead of spawning "
        "a fresh one (set by HostSupervisor.reconcile() when a previous runtime_host "
        "died but its watchdog process may have survived)",
    )
    parser.add_argument(
        "--adopt-watchdog-pid",
        type=int,
        default=None,
        help="PID of the watchdog process named by --adopt-watchdog-id",
    )
    parser.add_argument(
        "--adopt-watchdog-control-port",
        type=int,
        default=None,
        help="Authenticated loopback control port of the watchdog to adopt",
    )
    parser.add_argument(
        "--lease-timeout-seconds",
        type=float,
        default=float(
            os.environ.get(
                "RUNTIME_HOST_LEASE_TIMEOUT_SECONDS",
                DEFAULT_LEASE_TIMEOUT_SECONDS,
            )
        ),
        help="Exit if the control plane does not renew the host lease within this many seconds",
    )
    parser.add_argument(
        "--driver",
        choices=("morelia",),
        default=os.environ.get("RUNTIME_DRIVER", "morelia"),
        help="Runtime driver to run (default: morelia)",
    )
    args = parser.parse_args()

    # Read the manifest once at startup; never re-read from user paths at runtime.
    with open(args.manifest, encoding="utf-8") as fh:
        manifest = Manifest.from_dict(json.load(fh))

    runtime_id = args.runtime_id or uuid4().hex
    # The immutable manifest supplies a default session identity for log calls
    # made by worker threads that do not inherit structlog contextvars.
    configure_logging(
        get_config(),
        stream=sys.stderr,
        diagnostic_layer="runtime-host",
        diagnostic_context={
            "session_id": manifest.session_id,
            "dataflow_id": manifest.dataflow_id,
            "runtime_id": runtime_id,
        },
    )

    # Build driver with a placeholder callback, then patch it once the host
    # exists so reports flow into the ring buffer.
    driver = _build_driver(
        manifest,
        manifest_path=args.manifest,
        driver_name=args.driver,
        on_report=lambda _: None,
        runtime_id=runtime_id,
        ingest_url=args.ingest_url,
        ingest_token=args.ingest_token,
        outbox_dir=args.outbox_dir,
        hardware_lock_dir=args.hardware_lock_dir,
        control_token=args.token,
        adopt_watchdog_id=args.adopt_watchdog_id,
        adopt_watchdog_pid=args.adopt_watchdog_pid,
        adopt_watchdog_control_port=args.adopt_watchdog_control_port,
    )
    gate = LifecycleSafetyGate(manifest=manifest, driver=driver)
    lease = RuntimeHostLease(timeout_seconds=args.lease_timeout_seconds)
    host = DataflowRuntimeHost(
        gate=gate,
        manifest=manifest,
        driver=driver,
        port=args.port,
        token=args.token,
        runtime_id=runtime_id,
        ingest_url=args.ingest_url,
        ingest_token=args.ingest_token,
        lease=lease,
    )
    driver._on_report = host.collect_report

    stop_event = threading.Event()

    def _shutdown(signum, frame):  # noqa: ARG001
        stop_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Do not announce HTTP readiness until the supervised watchdog has passed
    # its own preflight. A replacement host that adopted a surviving watchdog
    # already has that proof and must not repeat the IDLE-only transition.
    try:
        _prepare_driver_for_host_start(driver)
        host.start()
        _log.info(
            "runtime_host_ready",
            session_id=manifest.session_id,
            dataflow_id=manifest.dataflow_id,
            runtime_id=runtime_id,
            pid=os.getpid(),
            terminal_phase=driver.phase.value,
            outcome="ready",
        )
    except Exception as exc:
        payload = {
            "error_type": str(getattr(exc, "error_type", type(exc).__name__))[:120],
            "message": str(getattr(exc, "reason", str(exc)))[:500],
            "device_id": getattr(exc, "device_id", None),
            "sink_id": getattr(exc, "sink_id", None),
        }
        print(f"ERROR:{json.dumps(payload, separators=(',', ':'))}", flush=True)
        with suppress(Exception):
            driver.close()
        sys.exit(1)

    # Flush immediately — the parent reads these two lines to learn the port.
    print(f"PORT:{host.port}", flush=True)
    print("READY", flush=True)

    while not stop_event.wait(
        timeout=get_config().RUNTIME_HOST_MAIN_LOOP_INTERVAL_SECONDS
    ):
        if lease.expired():
            stop_event.set()
            break

    host.stop()

    # An HTTP `stop` command (the daemon's normal path) already drives the
    # driver through its own stop() and emits a phase=STOPPED report. But
    # SIGTERM/SIGINT/lease-expiry can land WITHOUT a prior stop command — the
    # daemon crashed, or this host's lease simply timed out — leaving the
    # driver stuck at RUNNING/PREFLIGHT and no terminal report ever emitted.
    # Drive it now so at least the local report ring (and any northbound push
    # still able to land) gets a terminal row before close() tears resources
    # down. Best-effort: nothing here can guarantee delivery once the process
    # is on its way out, so a failure is logged, not fatal to shutdown.
    if driver.phase in _STOPPABLE_PHASES:
        try:
            driver.stop()
        except Exception:
            _log.error(
                "driver stop failed during shutdown",
                phase=driver.phase.value,
                exc_info=True,
            )

    driver.close()
    sys.exit(0)


if __name__ == "__main__":
    main()
