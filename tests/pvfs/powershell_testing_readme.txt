================================================================================
PVFS tests – PowerShell quick reference
================================================================================
This file covers running the PVFS tests (test_pvfs.py) and basic Python setup
from PowerShell. A similar reference for WSL and Linux is planned for a future
session.

--------------------------------------------------------------------------------
1. Python environment (PowerShell)
--------------------------------------------------------------------------------

From the repository root (e.g. E:\newPython\Morelia):

  Create a virtual environment (recommended):
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1

  Install the project (editable, for development):
    pip install -e .

  Install the project (normal install, not editable):
    pip install .

  Install test/optional dependencies (e.g. PyAV for PVFS tests):
    pip install -e ".[dev]"
  or see pyproject.toml / docs for the exact extra name.

  Upgrade the editable install after pulling changes:
    pip install -e . --upgrade --no-deps

Note: If you get "running scripts is disabled" when activating the venv, run:
  Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
  (See src/pvfs_tools/execution_policy.txt.)

--------------------------------------------------------------------------------
2. Running all tests in test_pvfs.py
--------------------------------------------------------------------------------

From the repository root, with your venv activated:

  Run every test in tests/pvfs/test_pvfs.py:
    pytest tests/pvfs/test_pvfs.py

  Same, with verbose output (one line per test):
    pytest tests/pvfs/test_pvfs.py -v

  Same, and show print() / stdout (no capture):
    pytest tests/pvfs/test_pvfs.py -v -s

  From the tests/pvfs directory:
    cd tests\pvfs
    pytest test_pvfs.py -v -s

--------------------------------------------------------------------------------
3. Running a specific test
--------------------------------------------------------------------------------

  By test name (exact function name):
    pytest tests/pvfs/test_pvfs.py -v -k "test_pvfs_get_channel_list"

  By substring (matches any test whose name contains the string):
    pytest tests/pvfs/test_pvfs.py -v -k "channel_list"
    pytest tests/pvfs/test_pvfs.py -v -k "database"

  Run a single test by full path (node id):
    pytest tests/pvfs/test_pvfs.py::test_pvfs_get_channel_list -v -s

  Run several tests by name with -k (AND/OR):
    pytest tests/pvfs/test_pvfs.py -v -k "get_channel_list or get_file_list"

--------------------------------------------------------------------------------
4. Useful pytest flags
--------------------------------------------------------------------------------

  -v, --verbose          One line per test; more detail with -vv.
  -s                     Don't capture stdout/stderr (see print, logs).
  -k EXPR                Run tests whose names match EXPR (e.g. "channel").
  -x                     Stop after the first failure.
  --lf                   Re-run only the last failures (after a previous run).
  -q, --quiet            Less output.
  --tb=short             Shorter tracebacks (default: auto).
  --tb=no                No tracebacks.
  -n auto                Run tests in parallel (needs pytest-xdist).

Examples:

  Verbose, show prints, stop at first failure:
    pytest tests/pvfs/test_pvfs.py -v -s -x

  Only tests whose names contain "pvfs_create":
    pytest tests/pvfs/test_pvfs.py -v -k "pvfs_create"

--------------------------------------------------------------------------------
5. Prerequisites for PVFS tests
--------------------------------------------------------------------------------

  - pvfs_tools must be installed (pip install -e . or pip install .).
  - 64-bit pvfs.dll and pvfs_wrapper.dll must be present in src/pvfs_tools/Core/
    (build with src/pvfs_tools/build_pvfs_x64.ps1 if needed).
  - PyAV is required; tests are skipped if PyAV is not installed.
  - Test data (e.g. sine.pvfs, video.pvfs) should be in tests/pvfs/; the repo
    may include sample files.

--------------------------------------------------------------------------------
6. Future reference
--------------------------------------------------------------------------------

  A similar reference for compiling the PVFS native libraries and running
  these tests under WSL and Linux will be added in a future session.

================================================================================
