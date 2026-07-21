"""Windows process-tree containment for the hardware-owning watchdog."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.runtime_host.watchdog_process_driver import pid_is_alive


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object behavior")
def test_killing_guarded_watchdog_terminates_its_child_process() -> None:
    """A hard-killed watchdog must not leave a Morelia-like child alive."""
    repository = Path(__file__).resolve().parents[1]
    helper = "\n".join(
        (
            "import subprocess",
            "import sys",
            "import time",
            "from app.watchdog_process.process_tree import install_process_tree_guard",
            "guard = install_process_tree_guard()",
            "child = subprocess.Popen(",
            "    [sys.executable, '-c', 'import time; time.sleep(60)'],",
            "    stdout=subprocess.DEVNULL,",
            "    stderr=subprocess.DEVNULL,",
            ")",
            "print(child.pid, flush=True)",
            "time.sleep(60)",
        )
    )
    watchdog = subprocess.Popen(
        [sys.executable, "-c", helper],
        cwd=repository,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    child_pid: int | None = None

    try:
        assert watchdog.stdout is not None
        line = watchdog.stdout.readline().strip()
        if not line:
            assert watchdog.stderr is not None
            pytest.fail(f"guarded watchdog did not start: {watchdog.stderr.read()}")
        child_pid = int(line)
        assert pid_is_alive(child_pid)

        watchdog.kill()
        watchdog.wait(timeout=5)

        deadline = time.monotonic() + 5
        while pid_is_alive(child_pid) and time.monotonic() < deadline:
            time.sleep(0.05)

        assert not pid_is_alive(child_pid)
    finally:
        if watchdog.poll() is None:
            watchdog.kill()
            watchdog.wait(timeout=5)
        if child_pid is not None and pid_is_alive(child_pid):
            subprocess.run(
                ["taskkill", "/F", "/PID", str(child_pid)],
                capture_output=True,
                check=False,
            )
