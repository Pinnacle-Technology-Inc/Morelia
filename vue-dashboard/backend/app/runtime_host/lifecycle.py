"""Lifecycle safety gate: maps inbound commands to one RuntimeControlDriver."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager

from app.runtime_child.driver import RuntimeControlDriver, RuntimePhase
from app.runtime_host.manifest import Manifest
from app.watchdog.adapters import CommandAcknowledgement
from app.watchdog.messages import CommandEnvelope


class CommandInFlight(Exception):
    """A lifecycle command is already running on this host."""


DATAFLOW_SCOPE_COMMANDS = frozenset({"start", "stop", "restart-all-streams"})


class ScopedLifecycleLocks:
    """In-process mirror of the durable operation conflict domains."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._dataflow_active = False
        self._active_streams: set[str] = set()

    def acquire(self, blocking: bool = False) -> bool:
        """Compatibility helper: acquire the dataflow-scope lock."""
        if blocking:
            raise ValueError("blocking acquire is not supported")
        with self._guard:
            if self._dataflow_active or self._active_streams:
                return False
            self._dataflow_active = True
            return True

    def release(self) -> None:
        """Compatibility helper: release the dataflow-scope lock."""
        with self._guard:
            self._dataflow_active = False

    def acquire_stream(self, target_device_id: str) -> bool:
        """Acquire the stream-scope lock for one device; False if unavailable.

        Unavailable means either a dataflow-scope command holds the whole
        dataflow, or this same stream is already busy. Paired with
        ``release_stream`` so a command can hold the lock across the
        asynchronous driver work (see ``LifecycleSafetyGate.accept``).
        """
        with self._guard:
            if self._dataflow_active or target_device_id in self._active_streams:
                return False
            self._active_streams.add(target_device_id)
            return True

    def release_stream(self, target_device_id: str) -> None:
        with self._guard:
            self._active_streams.discard(target_device_id)

    @contextmanager
    def dataflow(self) -> Iterator[None]:
        if not self.acquire(blocking=False):
            raise CommandInFlight("a dataflow-scope lifecycle command is already in flight")
        try:
            yield
        finally:
            self.release()

    @contextmanager
    def stream(self, target_device_id: str) -> Iterator[None]:
        with self._guard:
            if self._dataflow_active:
                raise CommandInFlight(
                    "a dataflow-scope lifecycle command is already in flight"
                )
            if target_device_id in self._active_streams:
                raise CommandInFlight(
                    f"a lifecycle command is already in flight for stream {target_device_id!r}"
                )
            self._active_streams.add(target_device_id)
        try:
            yield
        finally:
            with self._guard:
                self._active_streams.discard(target_device_id)


class LifecycleSafetyGate:
    """Dispatches validated watchdog commands to one owned RuntimeControlDriver."""

    def __init__(self, manifest: Manifest, driver: RuntimeControlDriver) -> None:
        self._manifest = manifest
        self._driver = driver
        self._lock = ScopedLifecycleLocks()
        self._device_ids = frozenset(df.device_id for df in manifest.device_flows)

    def handle(self, raw: Mapping[str, object]) -> CommandAcknowledgement:
        """Validate, run the driver work synchronously, and acknowledge.

        This is the direct/in-process path (used by tests and any caller that
        wants the command fully applied before it returns). The loopback HTTP
        server uses ``accept`` instead so it can ACK before the — potentially
        slow — driver work finishes (see ``DataflowRuntimeHost``).
        """
        envelope, run = self.accept(raw)
        run()
        return self.acknowledgement(envelope)

    def accept(self, raw: Mapping[str, object]) -> tuple[CommandEnvelope, Callable[[], None]]:
        """Validate a command and acquire its scope lock, synchronously.

        Returns ``(envelope, run)``. Everything that can cheaply fail — a
        malformed/unsupported envelope (``ValueError``) or a busy conflict
        domain (``CommandInFlight``) — is raised here, before any ACK, so the
        HTTP layer can still map those to 400/423. ``run`` performs the actual
        driver calls (preflight/start/stop/recover) and releases the scope lock
        when it finishes; it is the only part that touches hardware, and the
        only part safe to defer to a background thread.
        """
        envelope = CommandEnvelope.from_dict(raw)
        self._reject_stale_watchdog_target(envelope)

        if envelope.command in DATAFLOW_SCOPE_COMMANDS:
            work = self._plan_dataflow(envelope)
            if not self._lock.acquire():
                raise CommandInFlight(
                    "a dataflow-scope lifecycle command is already in flight"
                )
            release = self._lock.release
        else:
            device_id = self._validated_stream_target(envelope)
            recovery_id = envelope.correlation.recovery_id
            if recovery_id is None:
                raise ValueError(
                    f"recovery command {envelope.command!r} requires a recovery_id"
                )
            work = self._plan_recovery(recovery_id, device_id)
            if not self._lock.acquire_stream(device_id):
                raise CommandInFlight(
                    f"a lifecycle command is already in flight for stream {device_id!r}"
                )

            def release() -> None:
                self._lock.release_stream(device_id)

        def run() -> None:
            try:
                work()
            finally:
                release()

        return envelope, run

    def _reject_stale_watchdog_target(self, envelope: CommandEnvelope) -> None:
        """Reject a command whose target ``watchdog_id`` names a stale identity.

        ``self._driver`` may or may not currently supervise a watchdog process
        (``WatchdogProcessDriver``, packet 06) — ``getattr`` with a ``None``
        default keeps this a no-op for any driver that doesn't expose the
        attribute (e.g. an in-process driver with no separate watchdog
        process). It is also a no-op while the supervised driver has no
        active watchdog yet (fresh/IDLE, before its first ``start``) — there
        is nothing to be stale relative to, and a ``start`` command is
        exactly what causes a watchdog process to be spawned.

        Once the driver *does* have an active watchdog identity, any command
        naming a different one is rejected deterministically (``ValueError``,
        mapped to 400 by the HTTP layer — see ``server.py``) rather than
        forwarded to a watchdog process that is no longer the active one.
        """
        active_watchdog_id = getattr(self._driver, "watchdog_id", None)
        if active_watchdog_id is None:
            return
        target_watchdog_id = envelope.correlation.watchdog_id
        if target_watchdog_id != active_watchdog_id:
            raise ValueError(
                f"command {envelope.command!r} targets stale watchdog_id "
                f"{target_watchdog_id!r}; the active watchdog process is "
                f"{active_watchdog_id!r}"
            )

    @staticmethod
    def acknowledgement(envelope: CommandEnvelope) -> CommandAcknowledgement:
        return CommandAcknowledgement(
            status="accepted",
            command_id=envelope.correlation.command_id,
            watchdog_id=envelope.correlation.watchdog_id,
        )

    def _plan_dataflow(self, envelope: CommandEnvelope) -> Callable[[], None]:
        """Validate a dataflow-scope command and return its deferred driver work."""
        command = envelope.command
        if command == "start":

            def _start() -> None:
                # Runtime-host startup now performs preflight before its READY
                # handshake. Preserve the direct/in-process path for drivers
                # that are still IDLE, but never repeat PREFLIGHT on a host
                # that already crossed that barrier.
                if self._driver.phase is RuntimePhase.IDLE:
                    self._driver.preflight()
                self._driver.start()

            return _start
        if command == "stop":
            return self._driver.stop

        # restart-all-streams — validated up front so a bad envelope 400s before ACK.
        if envelope.target_device_id is not None:
            raise ValueError("restart-all-streams does not accept target_device_id")
        recovery_id = envelope.correlation.recovery_id
        if recovery_id is None:
            raise ValueError("restart-all-streams requires a recovery_id")
        device_ids = tuple(self._device_ids)

        def _restart_all() -> None:
            for device_id in device_ids:
                self._driver.recover(recovery_id, device_id)

        return _restart_all

    def _plan_recovery(self, recovery_id: str, device_id: str) -> Callable[[], None]:
        """Return the deferred driver work for a targeted stream recovery."""

        def _recover() -> None:
            self._driver.recover(recovery_id, device_id)

        return _recover

    def _validated_stream_target(self, envelope: CommandEnvelope) -> str:
        device_id = envelope.target_device_id
        if device_id is None:
            raise ValueError(
                f"recovery command {envelope.command!r} requires a target_device_id"
            )
        if device_id not in self._device_ids:
            raise ValueError(
                f"target_device_id {device_id!r} is not owned by this dataflow"
            )
        return device_id
