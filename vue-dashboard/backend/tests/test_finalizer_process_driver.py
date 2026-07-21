from io import StringIO

from app.finalizer_process.driver import FinalizerProcessDriver


class _Process:
    def __init__(self, returncode=None):
        self.stdout = StringIO("READY\n")
        self.returncode = returncode
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


def test_driver_restarts_an_exited_finalizer():
    processes = [_Process(returncode=1), _Process(returncode=None)]
    calls = []

    def popen(args, **kwargs):
        calls.append(args)
        return processes[len(calls) - 1]

    driver = FinalizerProcessDriver(
        config_name="testing",
        popen=popen,
        start_monitor=False,
    )
    driver.start()

    assert driver.check_and_restart() is True
    assert len(calls) == 2
    assert driver.process is processes[1]
    driver.stop()
    assert processes[1].terminated is True
