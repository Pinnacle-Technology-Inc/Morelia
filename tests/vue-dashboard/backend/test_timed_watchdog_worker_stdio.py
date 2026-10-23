"""Real process/pipe regression for dashboard worker logging ownership."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("redirect", [True, False], ids=["durable-log", "negative-control"])
def test_worker_and_descendant_stdout_survive_handshake_reader_loss(tmp_path, redirect):
    source = """
import subprocess
import sys
from app.runtime_child.acknowledged_dataflow import _redirect_worker_stdout_to_log
print('READY', flush=True)
if sys.argv[1] == 'redirect':
    _redirect_worker_stdout_to_log()
sys.stdin.read(1)
print('worker teardown', flush=True)
subprocess.run([sys.executable, '-c', "print('descendant teardown', flush=True)"], check=True)
"""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(Path(item).resolve()) for item in sys.path if item)}
    log_path = tmp_path / "worker.log"
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-c", source, "redirect" if redirect else "original"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, env=env)
        try:
            assert process.stdout.readline().strip() == b"READY"
            process.stdout.close()  # The host-owned reader disappears.
            process.stdin.write(b"x")
            process.stdin.flush()
            process.stdin.close()
            exitcode = process.wait(timeout=15)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    evidence = log_path.read_text(errors="replace")
    if redirect:
        assert exitcode == 0, evidence
        assert "worker teardown" in evidence
        assert "descendant teardown" in evidence
    else:
        assert exitcode != 0, "negative control must reproduce broken stdout"
        assert "OSError" in evidence or "BrokenPipeError" in evidence
