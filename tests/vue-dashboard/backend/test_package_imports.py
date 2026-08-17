import subprocess
import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from app.adapters.runtime_client import ControlPlaneCommandSender
from app.contracts.runtime_protocol import CommandEnvelope, Manifest, RuntimeReport
from app.domain.enums import SessionStatus
from app.domain.errors import UnknownConfigType
from app.watchdog.adapters import ControlPlaneCommandSender as WatchdogCommandSender

BACKEND_ROOT = Path(__file__).resolve().parents[3]
PYPROJECT = BACKEND_ROOT / "vue-dashboard/backend/pyproject.toml"
REQUIREMENTS_LOCK = BACKEND_ROOT / "vue-dashboard/backend/requirements.lock"

# Sink dependency groups declared in pyproject.toml. `all-sinks` is the
# aggregate that installs every optional sink at once.
SINK_EXTRAS = ("edf", "pvfs", "influx", "quest")
ALL_SINKS_EXTRA = "all-sinks"

# Optional sink libraries that must NOT be imported merely by importing the
# backend. These are the third-party (non-stdlib) top-level import names used by
# the Morelia EDF / PVFS / Influx / Quest sinks.
OPTIONAL_SINK_MODULES = ("pyedflib", "pvfs_tools", "influxdb_client", "reactivex")


def _load_pyproject() -> dict:
    print(BACKEND_ROOT)
    print(PYPROJECT)
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _read_lock_text() -> str:
    # requirements.lock is stored as UTF-16 (with BOM); tolerate UTF-8 too so a
    # future re-encode of the lock does not silently break this check.
    raw = REQUIREMENTS_LOCK.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def _locked_versions() -> dict[str, Version]:
    pins: dict[str, Version] = {}
    for line in _read_lock_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, _, ver = line.partition("==")
        pins[canonicalize_name(name.strip())] = Version(ver.strip())
    return pins


def test_package_clarity_import_surfaces_reexport_existing_types():
    assert ControlPlaneCommandSender is WatchdogCommandSender
    assert SessionStatus.PREPARING.value == "preparing"
    assert UnknownConfigType.__name__ == "UnknownConfigType"
    assert CommandEnvelope.__name__ == "CommandEnvelope"
    assert Manifest.__name__ == "Manifest"
    assert RuntimeReport.__name__ == "RuntimeReport"


def test_optional_sink_extras_declared():
    """Acceptance 1: explicit EDF/PVFS/Influx/Quest extras plus an aggregate."""
    extras = _load_pyproject()["project"]["optional-dependencies"]
    for group in (*SINK_EXTRAS, ALL_SINKS_EXTRA):
        assert group in extras, f"missing optional-dependency group: {group}"
        assert extras[group], f"optional-dependency group is empty: {group}"

    # The aggregate must pull in every individual sink extra (self-reference).
    aggregate = " ".join(extras[ALL_SINKS_EXTRA])
    for group in SINK_EXTRAS:
        assert group in aggregate, f"all-sinks does not include: {group}"


def test_base_import_does_not_require_optional_sink_libraries():
    """Acceptance 2: importing the backend must not import any optional sink lib.

    Run in a clean subprocess so the pytest process's own imports cannot mask a
    leak. The libraries are installed in this venv, so absence from sys.modules
    proves the backend did not import them, not that they are missing.
    """
    code = (
        "import sys\n"
        "import app  # noqa: F401\n"
        f"optional = {OPTIONAL_SINK_MODULES!r}\n"
        "leaked = sorted(m for m in optional if m in sys.modules)\n"
        "assert not leaked, 'backend imported optional sink libs: ' + repr(leaked)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_lock_and_pyproject_agree_on_sink_versions():
    """Acceptance 3: every pinned sink dependency satisfies its pyproject spec."""
    extras = _load_pyproject()["project"]["optional-dependencies"]
    pins = _locked_versions()
    project_name = canonicalize_name(_load_pyproject()["project"]["name"])

    checked = 0
    for group in SINK_EXTRAS:
        for spec in extras[group]:
            req = Requirement(spec)
            name = canonicalize_name(req.name)
            if name == project_name:
                continue  # self-reference, not a distribution pin
            assert name in pins, (
                f"{group} requires {req.name!r} but it is absent from "
                f"requirements.lock"
            )
            assert req.specifier.contains(pins[name], prereleases=True), (
                f"locked {req.name}=={pins[name]} does not satisfy "
                f"pyproject specifier {req.specifier} (group {group})"
            )
            checked += 1
    assert checked > 0, "no sink dependencies were checked"
