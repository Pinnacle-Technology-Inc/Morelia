"""Offline local diagnostics for the Pinnacle CLI."""

from __future__ import annotations

import importlib.util
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

import click
from flask import Flask
from sqlalchemy import inspect, text

from app.cli.daemon_client import DaemonClient, DaemonUnavailable
from app.config import Config, get_config
from app.control.supervisor import ensure_runtime_driver_ready
from app.database import db, init_database
from app.domain.enums import SinkType
from app.services.registry import sink_parameter_schema

# Backend root holds migrations/alembic.ini (app/cli/doctor.py -> parents[2]).
_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "migrations" / "alembic.ini"


def _migration_head() -> str:
    """Return the latest Alembic revision id, discovered from migrations/ on disk.

    Fails open: doctor is a never-crash diagnostic, so any discovery error
    (missing alembic.ini, empty tree, multiple heads) yields "unknown" instead
    of raising.
    """
    try:
        from alembic.config import Config as AlembicConfig
        from alembic.script import ScriptDirectory

        script = ScriptDirectory.from_config(AlembicConfig(str(_ALEMBIC_INI)))
        return script.get_current_head() or "unknown"
    except Exception:  # noqa: BLE001 - doctor reports head=unknown rather than failing
        return "unknown"


@click.command(name="doctor")
def doctor() -> None:
    """Print local diagnostic state without requiring the daemon."""
    for line in collect_doctor_lines():
        click.echo(line)


def collect_doctor_lines() -> list[str]:
    """Return stable, line-oriented diagnostics for CLI output.

    Sink readiness lines are informational only: a missing optional sink
    dependency (or an unsupported platform) never changes the ``doctor`` exit
    code. Doctor stays a never-fail diagnostic, and an unselected/unavailable
    sink must not fail general (CSV) backend readiness.
    """
    return [
        f"python: {platform.python_version()}",
        f"runtime: {sys.executable}",
        collect_runtime_driver_line(),
        *collect_db_lines(),
        collect_migration_line(),
        collect_daemon_line(),
        *collect_sink_lines(),
    ]


def collect_runtime_driver_line() -> str:
    driver = str(getattr(get_config(), "RUNTIME_DRIVER", "morelia"))
    if driver != "morelia":
        return f"runtime driver: {driver} (unsupported — only 'morelia' is valid)"

    try:
        ensure_runtime_driver_ready(driver)
    except Exception as exc:  # noqa: BLE001 - doctor reports readiness without failing
        return f"runtime driver: morelia unavailable ({_error_message(exc)})"
    return "runtime driver: morelia ready"


def collect_db_lines() -> list[str]:
    config = get_config()
    lines = [f"db uri: {_db_uri(config)}"]

    try:
        app = create_diagnostic_app()
        with app.app_context():
            tables = inspect(db.engine).get_table_names()
    except Exception as exc:  # noqa: BLE001 - doctor reports failures instead of failing
        lines.append(f"db: unavailable ({_error_message(exc)})")
        return lines

    lines.append(f"db: reachable (tables={len(tables)})")
    return lines


def collect_migration_line() -> str:
    head = _migration_head()
    try:
        app = create_diagnostic_app()
        with app.app_context():
            inspector = inspect(db.engine)
            if "alembic_version" not in inspector.get_table_names():
                current = "unversioned"
            else:
                current = (
                    db.session.execute(text("select version_num from alembic_version"))
                    .scalar()
                    or "unversioned"
                )
    except Exception as exc:  # noqa: BLE001 - doctor reports failures instead of failing
        return (
            f"migrations: head={head} current=unavailable "
            f"state=unknown ({_error_message(exc)})"
        )

    state = "up-to-date" if current == head else "not-at-head"
    return f"migrations: head={head} current={current} state={state}"


def collect_daemon_line() -> str:
    try:
        client = DaemonClient()
        client.get("/openapi.json")
    except DaemonUnavailable as exc:
        return f"daemon: unavailable ({_daemon_base_url(exc)})"
    except Exception as exc:  # noqa: BLE001 - daemon probe is informational only
        base_url = getattr(locals().get("client", None), "base_url", "<unknown>")
        return f"daemon: reachable ({base_url}, diagnostic warning: {_error_message(exc)})"

    return f"daemon: reachable ({client.base_url})"


# ---------------------------------------------------------------------------
# Per-sink readiness diagnostics
#
# Doctor reports every registered sink type independently with one of five
# stable status labels:
#
#   ready                 dependencies importable, platform supported, and no
#                         required per-session configuration is outstanding.
#   dependency-missing    an optional import for that sink is not installed on
#                         a supported platform; remediation names the extra.
#   configuration-required dependencies are ready but the sink has required
#                         config keys doctor cannot supply offline (e.g. the
#                         Influx ``api_token_env`` credential *reference*).
#   platform-unsupported  the sink's native library is unavailable on this OS
#                         (e.g. PVFS off Windows/Linux) — a platform constraint,
#                         not a hard error.
#   not-checked           the bounded probe raised unexpectedly; doctor never
#                         instantiates a sink or resolves a secret to find out.
#
# The import names probed (never the pip distribution names) and the extras map
# come from packet 08. Only ``importlib.util.find_spec`` is used: it discovers
# whether a module is importable without executing its top-level code, so no
# sink side effect (native binary load, socket, client) can run here.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SinkDependency:
    """Static dependency/platform metadata for one sink type (packet 08)."""

    extra: str | None
    imports: tuple[str, ...]
    distributions: tuple[str, ...]
    platforms: tuple[str, ...] | None
    note: str


# Import name -> distribution mapping mirrors pyproject's optional-dependency
# groups. csv/plot need no third-party install (stdlib / browser channel).
_SINK_DEPENDENCIES: dict[SinkType, _SinkDependency] = {
    SinkType.CSV: _SinkDependency(
        extra=None, imports=(), distributions=(), platforms=None, note="stdlib"
    ),
    SinkType.EDF: _SinkDependency(
        extra="edf",
        imports=("pyedflib", "numpy"),
        distributions=("pyEDFlib", "numpy"),
        platforms=None,
        note="",
    ),
    SinkType.PVFS: _SinkDependency(
        extra="pvfs",
        imports=("pvfs_tools",),
        distributions=("pypvfs",),
        platforms=("Windows", "Linux"),
        note="native library",
    ),
    SinkType.INFLUX: _SinkDependency(
        extra="influx",
        imports=("influxdb_client", "reactivex"),
        distributions=("influxdb-client", "reactivex"),
        platforms=None,
        note="",
    ),
    SinkType.QUEST: _SinkDependency(
        extra="quest",
        imports=("reactivex",),
        distributions=("reactivex",),
        platforms=None,
        note="ILP over stdlib socket",
    ),
    SinkType.PLOT: _SinkDependency(
        extra=None, imports=(), distributions=(), platforms=None, note="browser channel"
    ),
}


def collect_sink_lines() -> list[str]:
    """Return one readiness line per registered sink type (definition order)."""
    return [collect_sink_line(sink_type) for sink_type in SinkType]


def collect_sink_line(sink_type: SinkType) -> str:
    """Return the ``sink <type>: <status> (<detail>)`` diagnostic for one type."""
    dependency = _SINK_DEPENDENCIES[sink_type]
    try:
        schema = sink_parameter_schema(sink_type.value)
        category = str(schema["category"])
        required = tuple(schema["required"])
        status, detail = _evaluate_sink(dependency, category, required)
    except Exception as exc:  # noqa: BLE001 - doctor never fails; probe -> not-checked
        status, detail = "not-checked", f"probe error: {_error_message(exc)}"
    return f"sink {sink_type.value}: {status} ({detail})"


def _evaluate_sink(
    dependency: _SinkDependency, category: str, required: tuple[str, ...]
) -> tuple[str, str]:
    base = f"category={category}"

    # 1. Platform gate: an unsupported native library is a constraint, not a
    #    hard error, and is more actionable than a missing-import report.
    if dependency.platforms is not None and platform.system() not in dependency.platforms:
        allowed = " or ".join(dependency.platforms)
        return "platform-unsupported", (
            f"{base}; extra={dependency.extra} ({dependency.note}) requires "
            f"{allowed}; current platform: {platform.system()}"
        )

    # 2. Dependency gate: probe import names (not pip distributions).
    missing = [name for name in dependency.imports if not _probe_import(name)]
    if missing:
        plural = "s" if len(missing) > 1 else ""
        return "dependency-missing", (
            f"{base}; extra '{dependency.extra}' not installed; run "
            f"pip install 'guarded-experiment-backend[{dependency.extra}]'; "
            f"missing import{plural}: {', '.join(missing)}"
        )

    # 3. Configuration gate: dependencies are present but the sink declares
    #    required config keys doctor cannot satisfy offline. For Influx this is
    #    ``api_token_env`` — a credential *variable name*, never its value.
    if required:
        return "configuration-required", (
            f"{base}; extra={dependency.extra}; dependencies ready; "
            f"requires {', '.join(required)} (env-var name only; value not read)"
        )

    # 4. Ready.
    if dependency.extra:
        detail = f"{base}; extra={dependency.extra}; packages={', '.join(dependency.distributions)}"
    else:
        detail = f"{base}; {dependency.note}; no extra required"
    return "ready", detail


def _probe_import(name: str) -> bool:
    """Report whether *name* is importable, without executing its module body.

    ``find_spec`` performs bounded discovery only — it never runs the target
    module's top level, so probing (e.g.) ``pvfs_tools`` cannot load its native
    binary or otherwise cause a side effect.
    """
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _db_uri(config: type[Config]) -> str:
    value = getattr(config, "SQLALCHEMY_DATABASE_URI", None)
    return str(value) if value else "<unset>"


def create_diagnostic_app() -> Flask:
    """Create the minimum Flask app needed for database inspection."""
    app = Flask("pinnacle-doctor")
    app.config.from_object(get_config())
    init_database(app)
    return app


def _daemon_base_url(error: Exception) -> str:
    message = str(error)
    prefix = "daemon not running at "
    if message.startswith(prefix):
        return message.removeprefix(prefix)
    return message


def _error_message(error: Exception) -> str:
    return str(error) or error.__class__.__name__


__all__ = [
    "collect_daemon_line",
    "collect_db_lines",
    "collect_doctor_lines",
    "collect_migration_line",
    "collect_runtime_driver_line",
    "collect_sink_line",
    "collect_sink_lines",
    "create_diagnostic_app",
    "doctor",
]
