"""Finalizer process entrypoint — ``python -m app.finalizer_process``.

The dedicated, control-plane-owned worker that turns acquisition-complete
multi-component EDF/PVFS recordings into ONE published merged artifact. It is
deliberately the *least-privileged* process in the system:

- it owns NO hardware, NO Morelia/DataFlow runtime, NO sink handles, and no
  watchdog/runtime-host handles — it only opens the shared control-plane
  database (via ``app.database.create_database_app``) and, per merge attempt,
  temporary file handles owned by an injected merger;
- it performs one fenced merge attempt at a time through
  ``app.services.output_finalization.FinalizationCoordinator``; the fence token
  guarantees a superseded/duplicate finalizer can never publish.

Mirrors ``app/watchdog_process/__main__.py`` conventions: ``argparse`` args, a
``READY`` line on stdout once the loop is up (so a supervisor can detect
readiness without polling), structured logs on stderr (never stdout — that
would corrupt the handshake), and a SIGINT/SIGTERM signal loop. Exit code 0 on
a clean shutdown.

``--once`` runs a single scan-and-finalize cycle and exits, which the tests use
to drive the loop deterministically.
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from collections.abc import Callable

import structlog

from app.config import get_config
from app.database import create_database_app
from app.logging_config import configure_logging
from app.services.output_finalization import (
    FinalizationCoordinator,
    MergerRegistry,
    build_default_merger_registry,
    coordinator_from_config,
    reconcile_stopped_session_acquisitions,
    resolve_merger,
)

_log = structlog.get_logger(__name__)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Output Finalizer Process")
    parser.add_argument(
        "--worker-id",
        required=True,
        help="This finalizer instance's identity (used as the claim owner id)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Flask config name (default: FLASK_CONFIG env or 'development')",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=None,
        help="Idle poll interval seconds (default: FINALIZER_POLL_INTERVAL_SECONDS)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scan-and-finalize cycle, then exit",
    )
    return parser


def run_cycle(
    coordinator: FinalizationCoordinator,
    *,
    worker_id: str,
    registry: MergerRegistry,
    max_claims: int = 128,
) -> list:
    """Claim and finalize every currently claimable logical output.

    Returns the list of per-attempt outcomes. Each attempt claims the oldest
    claimable output, resolves a merger for its sink_type, and runs one fenced
    merge attempt. Bounded by ``max_claims`` so one cycle always terminates.
    """
    outcomes = []
    for _ in range(max_claims):
        # Peek at what would be claimed so we can resolve the right merger; the
        # coordinator re-claims atomically. To keep the merger dispatch simple
        # and fenced, claim first via a dispatching merger.
        outcome = coordinator.finalize_once(
            lambda request: resolve_merger(registry, request.sink_type)(request),
            worker_id=worker_id,
        )
        if outcome is None:
            break
        outcomes.append(outcome)
        log_method = _log.warning if outcome.action in {"failed", "blocked"} else _log.info
        log_method(
            "output_finalization_attempt",
            logical_sink_id=outcome.logical_sink_id,
            action=outcome.action,
            final_output_id=outcome.final_output_id,
            published_path=outcome.published_path,
            reason=outcome.reason,
        )
    return outcomes


def main(
    argv: list[str] | None = None,
    *,
    coordinator_factory: Callable[..., FinalizationCoordinator] | None = None,
    merger_registry: MergerRegistry | None = None,
    poll_interval_seconds: float | None = None,
) -> int:
    args = build_arg_parser().parse_args(argv)
    config = get_config(args.config)

    # stderr, not stdout: stdout carries the READY handshake.
    configure_logging(config, stream=sys.stderr)

    registry = build_default_merger_registry() if merger_registry is None else merger_registry
    if coordinator_factory is None:
        coordinator_factory = coordinator_from_config

    poll_interval = (
        (args.poll_interval if args.poll_interval is not None else config.FINALIZER_POLL_INTERVAL_SECONDS)
        if poll_interval_seconds is None
        else poll_interval_seconds
    )

    app = create_database_app(args.config)

    stop_event = threading.Event()
    partials_cleaned = False

    def _shutdown(signum, frame):  # noqa: ARG001
        stop_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Flush immediately — the supervisor reads this line to learn we are up.
    print("READY", flush=True)

    def _cycle() -> None:
        nonlocal partials_cleaned
        with app.app_context():
            coordinator = coordinator_factory(config)
            reconcile_stopped_session_acquisitions()
            cleanup_partials = getattr(coordinator, "cleanup_inactive_partials", None)
            if not partials_cleaned and cleanup_partials is not None:
                removed = cleanup_partials()
                partials_cleaned = True
                if removed:
                    _log.info("output_partial_cleanup_completed", removed=removed)
            run_cycle(coordinator, worker_id=args.worker_id, registry=registry)

    if args.once:
        _cycle()
        return 0

    while not stop_event.wait(timeout=poll_interval):
        _cycle()

    # One final drain on clean shutdown.
    _cycle()
    return 0


if __name__ == "__main__":
    sys.exit(main())
