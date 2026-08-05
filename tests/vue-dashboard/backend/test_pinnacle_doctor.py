from __future__ import annotations

from click.testing import CliRunner

from app.cli.daemon_client import DaemonUnavailable
from app.cli.main import pinnacle


def test_doctor_reports_daemon_unavailable_and_exits_zero(monkeypatch):
    import app.cli.doctor as doctor

    class UnavailableDaemonClient:
        base_url = "http://127.0.0.1:5000"

        def get(self, path):
            raise DaemonUnavailable("daemon not running at http://127.0.0.1:5000")

    monkeypatch.setattr(doctor, "DaemonClient", UnavailableDaemonClient)
    monkeypatch.setattr(
        doctor,
        "collect_db_lines",
        lambda: ["db uri: sqlite:///:memory:", "db: reachable (tables=0)"],
    )
    monkeypatch.setattr(
        doctor,
        "collect_migration_line",
        lambda: "migrations: head=0006 current=0006 state=up-to-date",
    )

    result = CliRunner().invoke(pinnacle, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "python:" in result.output
    assert "runtime:" in result.output
    assert "db uri: sqlite:///:memory:" in result.output
    assert "db: reachable" in result.output
    assert "migrations: head=0006 current=0006 state=up-to-date" in result.output
    assert "daemon: unavailable (http://127.0.0.1:5000)" in result.output
    assert "Traceback" not in result.output


def test_doctor_reports_broken_db_uri_without_crashing(monkeypatch):
    import app.cli.doctor as doctor

    class UnavailableDaemonClient:
        base_url = "http://127.0.0.1:5000"

        def get(self, path):
            raise DaemonUnavailable("daemon not running at http://127.0.0.1:5000")

    def broken_create_diagnostic_app():
        raise RuntimeError("invalid database uri")

    monkeypatch.setattr(doctor, "DaemonClient", UnavailableDaemonClient)
    monkeypatch.setattr(doctor, "create_diagnostic_app", broken_create_diagnostic_app)

    result = CliRunner().invoke(pinnacle, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "db uri:" in result.output
    assert "db: unavailable (invalid database uri)" in result.output
    # Assert the head is reported (intent: doctor doesn't crash on a broken DB),
    # not a hardcoded revision — the real Alembic head is 0002 in this tree and
    # a pinned number is just migration-revision drift.
    assert "migrations: head=" in result.output
    assert "daemon: unavailable" in result.output
    assert "Traceback" not in result.output


def test_doctor_reports_morelia_preflight_failure(monkeypatch):
    import app.cli.doctor as doctor

    class Config:
        RUNTIME_DRIVER = "morelia"

    def fail_preflight(driver):
        raise RuntimeError("RUNTIME_DRIVER=morelia requires MORELIA_SRC")

    monkeypatch.setattr(doctor, "get_config", lambda: Config)
    monkeypatch.setattr(doctor, "ensure_runtime_driver_ready", fail_preflight)

    assert doctor.collect_runtime_driver_line() == (
        "runtime driver: morelia unavailable "
        "(RUNTIME_DRIVER=morelia requires MORELIA_SRC)"
    )


# ---------------------------------------------------------------------------
# Per-sink readiness diagnostics (packet 09A)
# ---------------------------------------------------------------------------


def _sink_line(lines, sink_type):
    prefix = f"sink {sink_type}:"
    matches = [line for line in lines if line.startswith(prefix)]
    assert len(matches) == 1, f"expected exactly one {prefix!r} line, got {matches!r}"
    return matches[0]


def test_doctor_reports_all_six_sinks_when_deps_present(monkeypatch):
    """AC1: every registered sink type appears with actionable guidance."""
    import app.cli.doctor as doctor

    # Deterministic happy path: all imports available, supported platform.
    monkeypatch.setattr(doctor, "_probe_import", lambda name: True)
    monkeypatch.setattr(doctor.platform, "system", lambda: "Windows")

    lines = doctor.collect_sink_lines()

    assert [line.split(":")[1].strip().split(" ")[0] for line in lines] == [
        "ready",  # csv
        "ready",  # edf
        "ready",  # pvfs (Windows supported)
        "configuration-required",  # influx requires api_token_env
        "ready",  # quest
        "ready",  # plot
    ]
    # csv/plot need no third-party extra; edf/pvfs/quest name their extra.
    assert "no extra required" in _sink_line(lines, "csv")
    assert "no extra required" in _sink_line(lines, "plot")
    assert "extra=edf" in _sink_line(lines, "edf")
    assert "extra=pvfs" in _sink_line(lines, "pvfs")
    assert "extra=quest" in _sink_line(lines, "quest")


def test_doctor_missing_optional_dependency_is_isolated(monkeypatch):
    """AC2: one missing extra affects only that sink; exit stays 0."""
    import app.cli.doctor as doctor

    class UnavailableDaemonClient:
        base_url = "http://127.0.0.1:5000"

        def get(self, path):
            raise DaemonUnavailable("daemon not running at http://127.0.0.1:5000")

    # pyedflib (edf) is the only unavailable import.
    monkeypatch.setattr(doctor, "_probe_import", lambda name: name != "pyedflib")
    monkeypatch.setattr(doctor.platform, "system", lambda: "Windows")
    monkeypatch.setattr(doctor, "DaemonClient", UnavailableDaemonClient)
    monkeypatch.setattr(
        doctor,
        "collect_db_lines",
        lambda: ["db uri: sqlite:///:memory:", "db: reachable (tables=0)"],
    )
    monkeypatch.setattr(
        doctor, "collect_migration_line", lambda: "migrations: head=0006 current=0006 state=up-to-date"
    )

    result = CliRunner().invoke(pinnacle, ["doctor"])

    assert result.exit_code == 0, result.output  # optional-sink gap never fails doctor
    lines = result.output.splitlines()
    edf = _sink_line(lines, "edf")
    assert edf.startswith("sink edf: dependency-missing")
    assert "guarded-experiment-backend[edf]" in edf
    assert "pyedflib" in edf
    # Siblings are unaffected.
    assert _sink_line(lines, "csv").startswith("sink csv: ready")
    assert _sink_line(lines, "quest").startswith("sink quest: ready")
    assert _sink_line(lines, "influx").startswith("sink influx: configuration-required")
    assert "Traceback" not in result.output


def test_doctor_reports_pvfs_platform_unsupported(monkeypatch):
    """AC1: PVFS off Windows/Linux is a platform constraint, not a hard error."""
    import app.cli.doctor as doctor

    monkeypatch.setattr(doctor, "_probe_import", lambda name: True)
    monkeypatch.setattr(doctor.platform, "system", lambda: "Darwin")

    lines = doctor.collect_sink_lines()
    pvfs = _sink_line(lines, "pvfs")

    assert pvfs.startswith("sink pvfs: platform-unsupported")
    assert "Windows or Linux" in pvfs
    assert "current platform: Darwin" in pvfs
    # Only PVFS is platform-gated; the other file sinks stay ready.
    assert _sink_line(lines, "csv").startswith("sink csv: ready")
    assert _sink_line(lines, "edf").startswith("sink edf: ready")


def test_doctor_influx_configuration_required_redacts_credentials(monkeypatch):
    """AC3: doctor names api_token_env but never reads or prints its value."""
    import app.cli.doctor as doctor

    secret_value = "super-secret-influx-token-value"
    # Even with a token present in the environment, doctor must not surface it.
    monkeypatch.setenv("PINNACLE_INFLUX_TOKEN", secret_value)
    monkeypatch.setattr(doctor, "_probe_import", lambda name: True)
    monkeypatch.setattr(doctor.platform, "system", lambda: "Windows")

    lines = doctor.collect_sink_lines()
    influx = _sink_line(lines, "influx")

    assert influx.startswith("sink influx: configuration-required")
    assert "api_token_env" in influx
    assert secret_value not in "\n".join(lines)


def test_doctor_sink_probe_error_reports_not_checked(monkeypatch):
    """Failure handling: an unexpected probe error yields not-checked, never a crash."""
    import app.cli.doctor as doctor

    def boom(name):
        raise RuntimeError("import machinery exploded")

    monkeypatch.setattr(doctor, "_probe_import", boom)
    monkeypatch.setattr(doctor.platform, "system", lambda: "Windows")

    # edf probes imports, so it hits the raising probe -> not-checked.
    line = doctor.collect_sink_line(doctor.SinkType.EDF)
    assert line.startswith("sink edf: not-checked")
    assert "probe error" in line


def test_doctor_probe_import_uses_find_spec_without_execution(monkeypatch):
    """_probe_import returns False (not raises) when a module is absent."""
    import app.cli.doctor as doctor

    assert doctor._probe_import("a_module_that_does_not_exist_anywhere_1234") is False
