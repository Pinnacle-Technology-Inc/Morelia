"""Opt-in transport boundary emulator inherited by Windows spawned children.

No runtime, sink, lifecycle or clock is replaced. Only fictional fixture ports are openable.
"""
import json
import os
import sys
import time
from pathlib import Path

if os.environ.get("TIMED_SERIAL_HARNESS"):
    import serial
    import serial.tools.list_ports
    from serial.tools.list_ports_common import ListPortInfo

    def packet(command, payload=b""):
        body = f"{command:04X}".encode() + payload
        return b"\x02" + body + f"{(~sum(body)) & 255:02X}".encode() + b"\x03"

    def record(event, **values):
        root = Path(os.environ["TIMED_SERIAL_HARNESS"])
        with (root / f"serial-{os.getpid()}.jsonl").open("a") as handle:
            handle.write(json.dumps({"event": event, "pid": os.getpid(), "utc": time.time(), **values}) + "\n")

    class Serial:
        def __init__(self, port=None, baudrate=9600, timeout=1, **kwargs):
            self.port, self.baudrate, self.timeout = port, baudrate, timeout
            self.write_timeout = 5
            self.is_open = False
            self.buffer = bytearray()
            self.streaming = False
            self.sequence = 0
            self.next_sample = 0
            self.paused = False
            self.name = port
            if port is not None:
                self.open()

        def open(self):
            if self.port not in {f"COM{int(os.environ.get('TIMED_SERIAL_PORT_BASE', '991')) + index}" for index in range(int(os.environ.get("TIMED_FIXTURE_DEVICES", "1")))}:
                raise serial.SerialException(f"Harness forbids real hardware: {self.port}")
            self.name = self.port
            self.is_open = True
            record("open", port=self.port)

        def close(self):
            if self.is_open:
                record("close", port=self.port)
            self.is_open = False

        def write(self, data):
            assert data[:1] == b"\x02" and data[-1:] == b"\x03", data
            command = int(data[1:5], 16)
            payload = data[5:-3]
            assert packet(command, payload) == data, data
            record("command", command=command, payload=payload.decode())
            response = {8: b"30", 9: b"", 12: b"01000001", 100: b"0064", 102: b"0028", 107: b"00", 110: b"00"}.get(command, b"")
            if command == 6:
                self.streaming = int(payload, 16) != 0
                response = payload
                if self.streaming:
                    self.next_sample = time.monotonic() + float(os.environ.get("TIMED_SERIAL_START_DELAY", "0")) + (2 if self.port == f"COM{int(os.environ.get('TIMED_SERIAL_PORT_BASE', '991')) + 1}" else 0)
            self.buffer.extend(packet(command, response))
            return len(data)

        def _generate(self):
            if self.streaming and time.monotonic() >= self.next_sample:
                if (Path(os.environ["TIMED_SERIAL_HARNESS"]) / "disconnect").exists():
                    if not self.paused:
                        record("transport_pause", port=self.port)
                        self.paused = True
                    return
                if self.paused:
                    record("transport_resume", port=self.port)
                    self.paused = False
                self.buffer.extend(packet(180, bytes([self.sequence % 256, 0, 0, 128, 0, 128, 0, 128])))
                self.sequence += 1
                self.next_sample = time.monotonic() + .01
                if self.sequence == 1:
                    record("first_sample")

        def read(self, size=1):
            deadline = time.monotonic() + (self.timeout or .01)
            while len(self.buffer) < size and time.monotonic() < deadline:
                self._generate()
                time.sleep(.001)
            result = bytes(self.buffer[:size])
            del self.buffer[:size]
            return result

        @property
        def in_waiting(self):
            self._generate()
            return len(self.buffer)

        def reset_input_buffer(self):
            self.buffer.clear()

        def reset_output_buffer(self):
            pass

        def flush(self):
            pass

    def ports(*args, **kwargs):
        result = []
        for index in range(int(os.environ.get("TIMED_FIXTURE_DEVICES", "1"))):
            port = ListPortInfo(f"COM{int(os.environ.get('TIMED_SERIAL_PORT_BASE', '991')) + index}")
            port.serial_number = "INDEPENDENT-TIMED-8206" + (f"-{index}" if index else "")
            port.description = "Pinnacle 8206HR independent transport fixture"
            port.vid, port.pid = 0x0403, 0x6001
            result.append(port)
        return result

    serial.Serial = Serial
    serial.tools.list_ports.comports = ports

    # Discovery must never enumerate or open attached native hardware either.
    # Keep the real native adapter intact; block only its external SDK boundary.
    def deny_native_open(*args, **kwargs):
        raise PermissionError("Independent serial harness forbids all real FTDI/native opens")

    try:
        import ftd2xx
        ftd2xx.createDeviceInfoList = lambda *args, **kwargs: 0
        ftd2xx.listDevices = lambda *args, **kwargs: []
        ftd2xx.getDeviceInfoList = lambda *args, **kwargs: []
        ftd2xx.getDeviceInfoDetail = deny_native_open
        ftd2xx.open = deny_native_open
        ftd2xx.openEx = deny_native_open
        # Backend safe-open owns the raw handle before wrapper construction.
        # Block that DLL boundary too, even if a test supplies a native identity.
        from ftd2xx import ftd2xx as native_wrapper
        native_wrapper._ft.FT_OpenEx = deny_native_open
        native_wrapper._ft.FT_Open = deny_native_open
    except (ImportError, OSError):
        pass
    try:
        import pylibftdi
        class EmptyNativeDriver:
            def list_devices(self, *args, **kwargs):
                return []
        pylibftdi.Driver = EmptyNativeDriver
        pylibftdi.Device = deny_native_open
    except (ImportError, OSError):
        pass

    # Deliberate, opt-in negative controls. Never enabled in passing baselines;
    # defects live in this test harness and never edit the production tree.
    mutation = os.environ.get("TIMED_NEGATIVE_CONTROL")
    # Short-lived SDK queue probes have a production two-second deadline.
    # They do not own any mutated behavior and must not import the full runtime.
    queue_helper = any('queue_server.py' in argument for argument in getattr(sys, 'orig_argv', sys.argv))
    if mutation and not queue_helper:
        from app.watchdog_process.process import WatchdogProcess, elapsed_clock
        record("negative_control", mutation=mutation)
        if mutation == "disable_expiry":
            WatchdogProcess._deadline_loop = lambda self: self._timer_closed.wait()
        elif mutation == "reset_recovery_window":
            original_restore = WatchdogProcess.restore_timing
            def reset_window(self, evidence):
                original_restore(self, evidence)
                self._deadline_elapsed = elapsed_clock()[2] + self._manifest.duration_seconds
            WatchdogProcess.restore_timing = reset_window
        elif mutation == "suppress_shutdown_ack":
            from app.runtime_child.acknowledged_dataflow import ShutdownReporter
            original_emit = ShutdownReporter.emit
            def suppress_receipt(self, phase, action, **kwargs):
                if phase.value in {"sinks_finalized", "worker_exiting"}:
                    return None
                return original_emit(self, phase, action, **kwargs)
            ShutdownReporter.emit = suppress_receipt
        elif mutation == "allow_post_expiry_respawn":
            from app.runtime_host.watchdog_process_driver import WatchdogProcessDriver
            WatchdogProcessDriver._replacement_blocked = lambda self: False
        else:
            raise ValueError(f"Unknown negative control: {mutation}")
