"""Dashboard POD adapters; the SDK's device classes remain unchanged.

Model constructors and decoders are inherited. The cooperative acquisition base
intercepts only the final Pod initialization, so no legacy PacketManager or USB
handle is constructed in the parent. Queues cross the spawn boundary in source
snapshots, never in persisted manifests.
"""

from __future__ import annotations

import inspect
import multiprocessing
import os
from contextlib import nullcontext
from functools import partial
from queue import Queue

from Morelia.Commands import CommandSet
from Morelia.Devices import AcquisitionDevice as LegacyAcquisitionDevice
from Morelia.Devices import Pod as LegacyPod
from Morelia.Devices import Pod8206HR as LegacyPod8206HR
from Morelia.Devices import Pod8401HR as LegacyPod8401HR
from Morelia.packet import ControlPacket


class Pod(LegacyPod):
    """Protocol-compatible POD with explicit backend I/O and local/shared queues."""

    _expected_type = None
    _backend_managed = True

    def __init__(
        self,
        port,
        baudrate=9600,
        device_name=None,
        use_d2xx=False,
        *,
        d2xx_serial_only=None,
        flow_control=None,
        read_timeout_ms=5000,
        write_timeout_ms=5000,
        startup_parameters=None,
        _control_queues=None,
        _queue_owner_pid=None,
        probe=False,
    ):
        options = getattr(self, "_managed_options", None) or {
            "d2xx_serial_only": d2xx_serial_only,
            "flow_control": flow_control,
            "read_timeout_ms": read_timeout_ms,
            "write_timeout_ms": write_timeout_ms,
            "startup_parameters": startup_parameters,
            "_control_queues": _control_queues,
            "_queue_owner_pid": _queue_owner_pid,
            "probe": probe,
        }
        if isinstance(baudrate, bool) or not isinstance(baudrate, int) or baudrate <= 0:
            raise ValueError("baudrate must be a positive integer")
        for key in ("read_timeout_ms", "write_timeout_ms"):
            value = options[key]
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{key} must be a positive integer")
        self._use_d2xx = bool(use_d2xx)
        if self._use_d2xx and options["d2xx_serial_only"] is False:
            raise ValueError("Managed native PODs require exact serial addressing")
        self._d2xx_serial_only = self._use_d2xx
        self._flow_control = options["flow_control"] or ("rts_cts" if use_d2xx else "none")
        if self._flow_control not in ("none", "rts_cts"):
            raise ValueError("Unsupported managed flow control")
        self._read_timeout_ms = options["read_timeout_ms"]
        self._write_timeout_ms = options["write_timeout_ms"]
        self._port_value = port
        self._name = str(port)
        self._device_name = device_name if device_name is not None else str(port)
        self._baudrate = baudrate
        self._port = None
        self._manager = None
        self._commands = CommandSet()
        self._control_packet_factory = partial(ControlPacket, self._commands)
        self._startup_parameters = dict(options["startup_parameters"] or {})
        self._last_command_failure = None
        self._last_transport_read_failure = None
        self._prepared = False
        self._preparing = False
        self._probe = bool(options["probe"])
        self._owns_queues = options["_control_queues"] is None and not self._probe
        self._queue_owner_pid = options["_queue_owner_pid"] or os.getpid()
        if options["_control_queues"] is not None:
            self._write_queue, self._read_queue = options["_control_queues"]
        elif self._probe:
            self._write_queue, self._read_queue = Queue(), Queue()
        else:
            context = multiprocessing.get_context("spawn")
            self._write_queue, self._read_queue = context.Queue(), context.Queue()
        self._queues_cleaned = False

    def obtain_write_queue(self):
        return self._write_queue

    def obtain_read_queue(self):
        return self._read_queue

    def initialize_control_queue(self):
        """Queues already belong to this source; never start a socket server."""

    def register_control_queue(self):
        """Spawn reconstruction supplies the existing pair directly."""

    def open_port(self, *, configure=True):
        """Open here, then validate/apply settings before any STREAM command.

        Recovery/preflight may explicitly pass configure=False when it only
        needs an open handle; the next prepare_acquisition applies settings.
        """
        if self._port is not None:
            if configure:
                self.prepare_acquisition()
            return
        from app.discovery.ftdi_transport import D2XXPortIO, VcpPortIO

        options = {
            "flow_control": self._flow_control,
            "read_timeout_ms": self._read_timeout_ms,
            "write_timeout_ms": self._write_timeout_ms,
        }
        if self._use_d2xx:
            options["d2xx_serial_only"] = True
        port_type = D2XXPortIO if self._use_d2xx else VcpPortIO
        try:
            self._port = port_type(self._port_value, self._baudrate, **options)
            self._prepared = False
            if configure:
                self.prepare_acquisition()
        except BaseException:
            self.close_port()
            raise

    def close_port(self):
        current = self._port
        self._prepared = False
        if current is not None:
            current.close_serial_port()
        elif self._use_d2xx:
            # A failed constructor may own a native handle before assignment to
            # self._port. The backend retains that owner until close succeeds.
            from app.discovery.ftdi_transport import retry_pending_cleanup
            retry_pending_cleanup(self._port_value)
        self._port = None

    def open_port_for_reset(self):
        self.open_port(configure=False)

    def prepare_acquisition(self):
        if self._expected_type is None or self._prepared or self._preparing:
            return
        if self._port is None:
            raise RuntimeError("The worker must open the device before configuring it")
        self._preparing = True
        try:
            response = self.write_read("TYPE", timeout_sec=min(self._read_timeout_ms / 1000, 2))
            if tuple(response.payload) != (self._expected_type,):
                raise ValueError(f"POD TYPE does not match expected model {self._expected_type}")
            for name, value in self._startup_parameters.items():
                descriptor = inspect.getattr_static(type(self), name, None)
                if not isinstance(descriptor, property) or descriptor.fset is None:
                    raise ValueError(f"Unsupported startup parameter {name!r}")
                self._last_command_failure = None
                setattr(self, name, value)
                if self._last_command_failure is not None:
                    raise RuntimeError(
                        f"Failed to configure {name}"
                    ) from self._last_command_failure
            self._prepared = True
        finally:
            self._preparing = False

    def _deadline(self, timeout_sec):
        return self._port.deadline(timeout_sec) if self._port is not None else nullcontext()

    def write_read(self, cmd, payload=None, validate_checksum=True, timeout_sec=5):
        self._last_transport_read_failure = None
        try:
            with self._deadline(timeout_sec):
                response = super().write_read(cmd, payload, validate_checksum, timeout_sec)
            if self._last_transport_read_failure is not None:
                raise self._last_transport_read_failure
            return response
        except Exception as exc:
            failure = self._last_transport_read_failure or exc
            self._last_command_failure = failure
            if failure is not exc:
                raise failure from exc
            raise

    def read_pod_packet(self, validate_checksum=True, timeout_sec=5):
        try:
            with self._deadline(timeout_sec):
                return super().read_pod_packet(validate_checksum, timeout_sec)
        except OSError as exc:
            # The SDK retries packet errors, including OSError. Preserve physical
            # I/O failures so a driver error cannot be reported as a TYPE timeout.
            if not isinstance(exc, TimeoutError):
                self._last_transport_read_failure = exc
            raise

    def _connection_snapshot(self):
        return {
            "d2xx_serial_only": self._d2xx_serial_only,
            "flow_control": self._flow_control,
            "read_timeout_ms": self._read_timeout_ms,
            "write_timeout_ms": self._write_timeout_ms,
            "startup_parameters": dict(self._startup_parameters),
            "_control_queues": (self._write_queue, self._read_queue),
            "_queue_owner_pid": self._queue_owner_pid,
            "probe": self._probe,
        }

    def get_dict(self):
        return {
            "port": self.port,
            "baudrate": self.baudrate,
            "device_name": self.device_name,
            "use_d2xx": self._use_d2xx,
            **self._connection_snapshot(),
        }

    def cleanup(self):
        self.close_port()
        if (
            self._owns_queues
            and self._queue_owner_pid == os.getpid()
            and not self._queues_cleaned
        ):
            closed = getattr(self, "_closed_queue_ids", set())
            self._closed_queue_ids = closed
            for queue in (self._write_queue, self._read_queue):
                if id(queue) in closed:
                    continue
                queue.cancel_join_thread()
                queue.close()
                closed.add(id(queue))
            self._queues_cleaned = True


class _BackendAcquisition(LegacyAcquisitionDevice, Pod):
    """Insert the backend Pod before SDK Pod in the cooperative MRO."""


class _ManagedModel:
    def __init__(
        self,
        *args,
        d2xx_serial_only=None,
        flow_control=None,
        read_timeout_ms=5000,
        write_timeout_ms=5000,
        startup_parameters=None,
        _control_queues=None,
        _queue_owner_pid=None,
        probe=False,
        **kwargs,
    ):
        self._managed_options = {
            "d2xx_serial_only": d2xx_serial_only,
            "flow_control": flow_control,
            "read_timeout_ms": read_timeout_ms,
            "write_timeout_ms": write_timeout_ms,
            "startup_parameters": startup_parameters,
            "_control_queues": _control_queues,
            "_queue_owner_pid": _queue_owner_pid,
            "probe": probe,
        }
        try:
            super().__init__(*args, **kwargs)
            if self._sample_rate is not None:
                self._startup_parameters.setdefault("sample_rate", self._sample_rate[0])
        except BaseException:
            if hasattr(self, "_owns_queues"):
                self.cleanup()
            raise

    def get_dict(self):
        return {**super().get_dict(), **self._connection_snapshot()}

    def read_pod_packet_streaming(self, timeout_sec=0.1, validate_checksum=True):
        with self._deadline(timeout_sec):
            return super().read_pod_packet_streaming(timeout_sec, validate_checksum)

    def __exit__(self, *args, **kwargs):
        with self._deadline(2):
            return super().__exit__(*args, **kwargs)


class Pod8206HR(_ManagedModel, LegacyPod8206HR, _BackendAcquisition):
    _expected_type = 48


class Pod8401HR(_ManagedModel, LegacyPod8401HR, _BackendAcquisition):
    _expected_type = 49


__all__ = ["Pod", "Pod8206HR", "Pod8401HR"]
