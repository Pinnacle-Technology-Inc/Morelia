"""Live CLI smoke harness — boot a REAL daemon, drive every command, raise on crash.

The thing you do by hand, automated: print a scenario, start the daemon, run each
command so you can SEE the behavior scroll past, and fail loudly the moment a
command *crashes* (unhandled traceback / abnormal exit) rather than merely
returning a handled validation error.

Run it:

    venv\\Scripts\\python.exe -m tests.smoke_cli
    venv\\Scripts\\python.exe -m tests.smoke_cli --only "read-only"   # one scenario
    venv\\Scripts\\python.exe -m tests.smoke_cli --keep-daemon        # leave it up

This drives the REAL entry point through subprocess (not Click's CliRunner), so
it exercises real HTTP round-trips to the daemon and real exit codes — the same
path you hit testing manually. It shares ONE SQLite DB + serial ports with any
other control plane, so, like the hardware checkpoint, it refuses to run while a
`pinnacle start` daemon is already up (see docs in memory: shared DB + ports).

Nothing here touches hardware: the default scenarios are read-only / offline
commands (list, status, doctor, validate, template list). Add hardware scenarios
behind a flag once these pass.
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

# The CLI is invoked exactly as a user would, via the installed module entry point.
_CLI = [sys.executable, "-m", "app.cli.main"]


@dataclass
class Command:
    """One CLI invocation inside a scenario.

    ``argv`` is everything after ``pinnacle`` (e.g. ``["session", "list"]``).
    ``expect_failure`` marks a command that is SUPPOSED to exit non-zero (a
    handled validation error, e.g. ``session start 999999`` on a missing id) — it
    is still a pass as long as it fails *cleanly* rather than crashing.
    """

    argv: list[str]
    note: str = ""
    expect_failure: bool = False


@dataclass
class Scenario:
    name: str
    description: str
    commands: list[Command] = field(default_factory=list)


@dataclass
class Result:
    command: Command
    exit_code: int
    stdout: str
    stderr: str


# ---------------------------------------------------------------------------
# Scenarios — the scripted behavior you want to watch scroll past.
# ---------------------------------------------------------------------------
SCENARIOS: list[Scenario] = [
    Scenario(
        name="read-only",
        description="Every listing / status command against a live but idle daemon.",
        commands=[
            Command(["status"], note="daemon should report running"),
            Command(["doctor"], note="environment self-check"),
            Command(["device", "list"]),
            Command(["device", "template", "list"]),
            Command(["session", "list"]),
            Command(["session", "template", "list"]),
            Command(["operation", "list"]),
            Command(["incident", "list"]),
            Command(["gap", "list"]),
            Command(["runtime", "list"]),
        ],
    ),
    Scenario(
        name="expected-errors",
        description="Commands that SHOULD fail — must fail cleanly, never crash.",
        commands=[
            Command(
                ["session", "status", "999999"],
                note="missing session id",
                expect_failure=True,
            ),
            Command(
                ["session", "start", "999999"],
                note="cannot start a session that does not exist",
                expect_failure=True,
            ),
            Command(
                ["device", "name", "999999", "whatever"],
                note="rename a device that does not exist",
                expect_failure=True,
            ),
        ],
    ),
]


def _run(command: Command, timeout: float) -> Result:
    proc = subprocess.run(
        _CLI + command.argv,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return Result(command, proc.returncode, proc.stdout, proc.stderr)


# ---------------------------------------------------------------------------
# CONTRIBUTION NEEDED — the heart of the harness.
#
# This function decides whether a Result is a *crash* (fail the run) or an
# acceptable outcome (keep going). It's the one real judgement call here, and it
# shapes how noisy vs. how strict the whole harness is.
#
# The relevant facts about THIS CLI (see app/cli/output.py + lifecycle.py):
#   - A handled error goes through ``exit_with_error`` -> ``click.ClickException``,
#     which Click prints to stderr as a line starting with ``Error: `` and exits 1.
#     That is EXPECTED behavior, not a crash.
#   - An UNHANDLED exception prints a Python traceback — stderr contains
#     ``Traceback (most recent call last):`` — and exits 1 as well.
#   - A process killed by a signal / access violation exits with a negative or
#     large code (e.g. -11, or 3221225477 on Windows).
#   - ``result.command.expect_failure`` tells you the caller EXPECTED a non-zero
#     exit for this specific command.
#
# Trade-offs to weigh:
#   - Keying only on exit code can't tell a clean validation error (exit 1) from a
#     traceback (also exit 1) — you'd either miss real crashes or flag every
#     expected error.
#   - Keying on the traceback marker in stderr catches unhandled exceptions
#     precisely, but won't catch a segfault that prints nothing — so you likely
#     want BOTH a traceback check AND an abnormal-exit-code check.
#   - How should ``expect_failure`` factor in? A command marked expect_failure
#     that exits 0 is arguably ALSO a failure (it should have errored) — decide
#     whether you care.
#
# Implement the body. Return True if this Result should FAIL the run.
# ---------------------------------------------------------------------------
def is_crash(result: Result) -> bool:
    """Return True if ``result`` represents a crash that should fail the run."""
    # Killed by a signal / access violation: negative (POSIX) or a huge unsigned
    # code (Windows access-violation codes look like 3221225477).
    if result.exit_code < 0 or result.exit_code > 255:
        return True

    # An unhandled exception prints a Python traceback to stderr — a handled
    # click.ClickException prints "Error: ..." instead and never this marker.
    if "Traceback (most recent call last):" in result.stderr:
        return True

    # A command we expected to fail cleanly, but it exited 0 instead: the
    # validation path we meant to exercise never fired.
    if result.command.expect_failure and result.exit_code == 0:
        return True

    return False


def _print_result(result: Result, crashed: bool) -> None:
    cmd = "pinnacle " + " ".join(result.command.argv)
    tag = "CRASH" if crashed else ("ok(expected-fail)" if result.command.expect_failure else "ok")
    header = f"  $ {cmd}"
    if result.command.note:
        header += f"    # {result.command.note}"
    print(header)
    for stream_name, body in (("stdout", result.stdout), ("stderr", result.stderr)):
        for line in body.splitlines():
            print(f"      {stream_name}| {line}")
    print(f"      -> exit {result.exit_code}  [{tag}]\n")


# ---------------------------------------------------------------------------
# Daemon lifecycle — start it, wait until it truly serves, always shut it down.
# ---------------------------------------------------------------------------
def _control_plane_url() -> str:
    from app.config import get_config

    return getattr(get_config(), "CONTROL_PLANE_BASE_URL", "http://127.0.0.1:5000")


def _is_serving(timeout: float = 0.5) -> bool:
    parsed = urlparse(_control_plane_url())
    host, port = parsed.hostname or "127.0.0.1", parsed.port or 5000
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _assert_no_live_daemon() -> None:
    if _is_serving():
        raise SystemExit(
            f"A control-plane daemon is already serving at {_control_plane_url()}.\n"
            "  This smoke run IS a control plane and shares its DB + serial ports.\n"
            "  Stop the existing 'pinnacle start' daemon, then re-run."
        )


def _start_daemon(wait_seconds: float = 15.0) -> None:
    print("[smoke] starting daemon...")
    proc = subprocess.run(_CLI + ["start"], capture_output=True, text=True, timeout=30)
    print(f"[smoke]   {proc.stdout.strip() or proc.stderr.strip()}")
    if proc.returncode != 0:
        raise SystemExit(f"[smoke] daemon failed to start (exit {proc.returncode})")
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if _is_serving():
            print("[smoke]   daemon is serving\n")
            return
        time.sleep(0.25)
    raise SystemExit("[smoke] daemon started but never began serving the port")


def _shutdown_daemon() -> None:
    print("[smoke] shutting down daemon...")
    proc = subprocess.run(
        _CLI + ["shutdown", "--force"], capture_output=True, text=True, timeout=30
    )
    print(f"[smoke]   {proc.stdout.strip() or proc.stderr.strip()}")


def run(scenarios: list[Scenario], *, command_timeout: float, keep_daemon: bool) -> int:
    _assert_no_live_daemon()
    _start_daemon()
    crashes: list[Result] = []
    try:
        for scenario in scenarios:
            print(f"\n=== SCENARIO: {scenario.name} ===")
            print(f"    {scenario.description}\n")
            for command in scenario.commands:
                result = _run(command, timeout=command_timeout)
                crashed = is_crash(result)
                _print_result(result, crashed)
                if crashed:
                    crashes.append(result)
    finally:
        if keep_daemon:
            print("[smoke] --keep-daemon set; leaving daemon running")
        else:
            _shutdown_daemon()

    print("\n=== SUMMARY ===")
    if crashes:
        print(f"FAILED — {len(crashes)} command(s) crashed:")
        for result in crashes:
            print(f"  - pinnacle {' '.join(result.command.argv)} (exit {result.exit_code})")
        return 1
    print("PASSED — no crashes.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Live CLI smoke harness")
    parser.add_argument("--only", help="Run only the scenario with this name")
    parser.add_argument(
        "--command-timeout",
        type=float,
        default=30.0,
        help="Per-command timeout in seconds",
    )
    parser.add_argument(
        "--keep-daemon",
        action="store_true",
        help="Leave the daemon running after the run (default: shut it down)",
    )
    args = parser.parse_args()

    scenarios = SCENARIOS
    if args.only:
        scenarios = [s for s in SCENARIOS if s.name == args.only]
        if not scenarios:
            raise SystemExit(f"no scenario named {args.only!r}")

    raise SystemExit(
        run(scenarios, command_timeout=args.command_timeout, keep_daemon=args.keep_daemon)
    )


if __name__ == "__main__":
    main()
