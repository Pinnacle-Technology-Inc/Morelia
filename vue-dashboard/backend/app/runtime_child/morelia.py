"""Morelia-backed runtime driver for one dataflow.

Importing this module does not load Morelia or touch hardware; that happens
only when ``MoreliaRuntime`` is constructed.
"""

from __future__ import annotations

import importlib
import os
import queue
import sys
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import contextmanager, suppress
from enum import Enum
from typing import Any

import structlog

from app.config import get_config
from app.domain.enums import CommsStatus, DeviceType, SinkType, StreamStatus
from app.runtime_child.driver import (
    DeviceReport,
    ReportCallback,
    RuntimePhase,
    RuntimeReport,
    SinkDeliveryState,
    SinkHealth,
    SinkReport,
)
from app.runtime_child.sink_factory import RuntimeContext, build_sink, build_sinks
from app.runtime_host.manifest import Manifest

_log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers passed into the DataFlow worker process (Windows spawn pickles them) so
# that we can add the sink error report object and track if data is being received 
# in Influx/Quest DB sink
# ---------------------------------------------------------------------------


def resolve_secret_from_env(env_var_name: str) -> str | None:
    """Look up an Influx token from an environment-variable *name*.

    The manifest stores the name, never the token. Called inside the worker
    just before the Influx client is built.
    """
    return os.environ.get(env_var_name)


def open_sink_delivery_outbox(path: str) -> Any:
    """Open a SQLite spool for samples that failed to reach Influx/Quest.

    Path-based so the worker opens its own handle; a live connection cannot
    cross the process boundary. Distinct from the watchdog telemetry outbox.
    """
    from app.watchdog_process.sink_delivery_outbox import SinkDeliveryOutbox

    return SinkDeliveryOutbox(path)


def _normalize_sink_error(event: object) -> dict[str, Any]:
    """Convert a Morelia ``SinkError`` (object or dict) into a plain dict."""
    if isinstance(event, Mapping):
        get = event.get  # type: ignore[assignment]
    else:
        def get(key: str, default: object = None) -> object:
            return getattr(event, key, default)

    return {
        "source_id": get("source_id"),
        "sink_id": get("sink_id"),
        "sink_class": get("sink_class"),
        "failure_kind": get("failure_kind"),
        "exception_type": get("exception_type"),
        "message": get("message"),
        "state": get("state"),
        "last_success_seq": get("last_success_seq"),
        "timestamp_ns": get("timestamp_ns"),
        "buffered_samples": get("buffered_samples", 0),
        "buffered_bytes": get("buffered_bytes", 0),
        "sample_loss": get("sample_loss", 0),
        "byte_loss": get("byte_loss", 0),
    }


def _normalize_source_status(event: object) -> dict[str, Any]:
    """Convert a source-read status event into a bounded plain dict."""
    if isinstance(event, Mapping):
        get = event.get  # type: ignore[assignment]
    else:
        def get(key: str, default: object = None) -> object:
            return getattr(event, key, default)

    return {
        "source_id": _bounded_text(get("source_id"), 160) or "unknown-source",
        "source_port": _bounded_text(get("source_port"), 160),
        "failure_kind": _bounded_text(get("failure_kind"), 120),
        "exception_type": _bounded_text(get("exception_type"), 120),
        "message": _bounded_text(get("message"), 500),
        "state": _bounded_text(get("state"), 80) or "degraded",
        "consecutive_failures": _sink_counter(get("consecutive_failures")),
        "timestamp_ns": get("timestamp_ns"),
    }


class _SinkErrorSender:
    """Enqueue a sink write failure for the parent to turn into a ``SinkReport``.

    Passed as Morelia's ``on_sink_error``. Separate from watchdog stream health:
    one destination can fail while samples still flow and sibling sinks succeed.
    Must stay picklable (module-level, queue only) and must not raise.
    """

    __slots__ = ("_queue",)

    def __init__(self, sink_error_queue: Any) -> None:
        self._queue = sink_error_queue

    def __call__(self, event: object) -> None:
        self._queue.put(_normalize_sink_error(event))


class _SourceErrorSender:
    """Enqueue a source-read status event for the parent to drain."""

    __slots__ = ("_queue",)

    def __init__(self, source_error_queue: Any) -> None:
        self._queue = source_error_queue

    def __call__(self, event: object) -> None:
        self._queue.put(_normalize_source_status(event))


def _default_sink_error_queue() -> Any:
    """Create a cross-process queue for sink-error events.

    Tests may inject an in-process ``queue.Queue`` instead.
    """
    import multiprocessing

    return multiprocessing.Queue()


def _default_source_error_queue() -> Any:
    """Create a cross-process queue for source-read status events."""
    import multiprocessing

    return multiprocessing.Queue()


def _sink_field(value: object, limit: int) -> str | None:
    """Return a truncated string field, or ``None`` if empty/non-str."""
    text = _bounded_text(value, limit)
    return text or None


def _sink_counter(value: object) -> int:
    """Return a non-negative int from worker data, else ``0``."""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def _import_morelia() -> tuple[type, type, type, type, type, type, type, type]:
    """Import Morelia classes, optionally via ``MORELIA_SRC`` on ``sys.path``."""

    morelia_src = os.environ.get("MORELIA_SRC")
    if morelia_src and morelia_src not in sys.path:
        sys.path.insert(0, morelia_src)

    watchdog_module = importlib.import_module("Morelia.Watchdog.watchdog")
    devices_module = importlib.import_module("Morelia.Devices")
    packet_module = importlib.import_module("Morelia.packet")
    dataflow_module = importlib.import_module("Morelia.Stream.data_flow")
    from app.output.managed_csv_sink import ManagedCsvSink

    return (
        watchdog_module.Watchdog,
        devices_module.Pod8206HR,
        devices_module.Pod8401HR,
        dataflow_module.DataFlow,
        ManagedCsvSink,
        devices_module.Preamp,
        packet_module.PrimaryChannelMode,
        packet_module.SecondaryChannelMode,
    )


def preflight_sink_dependencies(manifest: Manifest) -> None:
    """Check that optional packages for this manifest's sink types are installed.

    Only probes sinks listed in the manifest. Raises
    ``SinkDependencyMissing`` for the failing ``sink_id``; does not open
    hardware, files, or network connections.
    """
    from app.runtime_child.sink_factory import _require_dependencies

    for device_flow in manifest.device_flows:
        for sink_config in device_flow.sinks:
            _require_dependencies(sink_config)


class MoreliaRuntime:
    """Owns one Morelia DataFlow + Watchdog for a single dataflow."""

    def __init__(
        self,
        *,
        manifest: Manifest,
        on_report: ReportCallback,
        failure_threshold: int = 3,
        max_heartbeat_age_sec: float = 10.0,
        first_packet_timeout_sec: float | None = None,
        report_interval_sec: float = 3.0,
        stream_interval_sec: float = 1.0,
        timeout_sec: float = 5.0,
        shutdown_timeout_sec: float = 15.0,
        importer: Callable[
            [],
            tuple[type, type, type, type, type, type, type, type],
        ] = _import_morelia,
        sink_delivery_outbox_factory: Any | None = None,
        sink_error_queue_factory: Callable[[], Any] = _default_sink_error_queue,
        source_error_queue_factory: Callable[[], Any] = _default_source_error_queue,
    ) -> None:
        self._manifest = manifest
        self._on_report = on_report
        self._failure_threshold = failure_threshold
        self._max_heartbeat_age_sec = max_heartbeat_age_sec
        self._first_packet_timeout_sec = (
            max_heartbeat_age_sec
            if first_packet_timeout_sec is None
            else first_packet_timeout_sec
        )
        self._report_interval_sec = report_interval_sec
        self._stream_interval_sec = stream_interval_sec
        self._timeout_sec = timeout_sec
        self._shutdown_timeout_sec = shutdown_timeout_sec
        self._importer = importer
        # Factories the worker uses to open its own outbox / error queues.
        self._sink_delivery_outbox_factory = sink_delivery_outbox_factory
        self._sink_error_queue_factory = sink_error_queue_factory
        self._source_error_queue_factory = source_error_queue_factory

        self._phase = RuntimePhase.IDLE
        self._sequence = 0
        self._device_ids = tuple(df.device_id for df in manifest.device_flows)
        self._stream_by_device = {
            device_id: index for index, device_id in enumerate(self._device_ids)
        }

        self._pods: list[Any] = []
        self._sinks: list[Any] = []
        self._flowgraph: Any | None = None
        self._watchdog: Any | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._nonhealthy_streak_by_device = {device_id: 0 for device_id in self._device_ids}

        # Latest sink-write failures, kept separate from device/stream health.
        self._sink_error_queue: Any | None = None
        self._sink_reports: dict[tuple[str, str], SinkReport] = {}
        self._sink_seq: dict[tuple[str, str], int] = {}
        self._source_error_queue: Any | None = None
        self._source_status_by_device: dict[str, dict[str, object]] = {}
        self._device_id_by_port = {
            str(device_flow.port).lower(): device_flow.device_id
            for device_flow in manifest.device_flows
        }

    @property
    def phase(self) -> RuntimePhase:
        return self._phase

    def preflight(self) -> None:
        self._require(RuntimePhase.IDLE)
        with self._hardware_boundary("preflight"):
            self._build_stack()
            assert self._watchdog is not None
            self._watchdog.preflight(timeout_sec=self._timeout_sec)
        self._emit_all(StreamStatus.HEALTHY, phase=RuntimePhase.PREFLIGHT)

    def start(self) -> None:
        self._require(RuntimePhase.PREFLIGHT)
        assert self._flowgraph is not None
        assert self._watchdog is not None

        with self._hardware_boundary("start"):
            self._flowgraph.collect()
        self._phase = RuntimePhase.RUNNING
        self._emit_all(StreamStatus.HEALTHY, phase=RuntimePhase.RUNNING)
        self._watchdog_thread = threading.Thread(
            # watchdog.run() blocks; keep it off the command thread so we can still ack.
            target=self._run_watchdog,
            name=f"morelia-runtime-{self._manifest.dataflow_id}",
            daemon=True,
        )
        self._watchdog_thread.start()

    def recover(self, recovery_id: str, device_id: str) -> None:
        self._require(RuntimePhase.RUNNING)
        if device_id not in self._stream_by_device:
            raise ValueError(
                f"unknown device {device_id!r} for dataflow {self._manifest.dataflow_id!r}"
            )
        assert self._watchdog is not None

        stream_index = self._stream_by_device[device_id]
        monitor = getattr(self._watchdog, "dataflow_monitor", None)
        restart_one_stream = getattr(monitor, "restart_one_stream", None)
        if not callable(restart_one_stream):
            raise RuntimeError(
                "Morelia Watchdog does not expose dataflow_monitor.restart_one_stream()"
            )

        result = restart_one_stream(stream_index)
        if not result.get("ok"):
            raise RuntimeError(
                result.get("error") or result.get("status") or "Morelia recovery failed"
            )

        self._emit_from_watchdog_report(
            self._watchdog.get_report(verbose=True),
            recovery_id=recovery_id,
        )

    def stop(self) -> None:
        self._require(RuntimePhase.PREFLIGHT, RuntimePhase.RUNNING, RuntimePhase.STOPPED)
        if self._watchdog is not None:
            self._watchdog.stop()
            if self._watchdog_thread is not None:
                self._watchdog_thread.join(
                    timeout=self._timeout_sec + get_config().WATCHDOG_THREAD_JOIN_GRACE_SECONDS
                )
                self._watchdog_thread = None
            shutdown_error: Exception | None = None
            monitor = getattr(self._watchdog, "dataflow_monitor", None)
            stop_dataflow = getattr(monitor, "stop_dataflow", None)
            started_at = time.monotonic()
            if callable(stop_dataflow):
                try:
                    result = stop_dataflow(join_timeout_sec=self._shutdown_timeout_sec)
                    elapsed = time.monotonic() - started_at
                    self._emit_shutdown_transcript(result, elapsed_seconds=elapsed)
                    ok = not isinstance(result, Mapping) or result.get("ok") is True
                    forced = isinstance(result, Mapping) and result.get("forced_termination") is True
                    if not ok or forced:
                        shutdown_error = RuntimeError(
                            self._shutdown_failure_message(result)
                        )
                except Exception as exc:
                    shutdown_error = exc
                    _log.error(
                        "dataflow_shutdown_failed",
                        dataflow_id=self._manifest.dataflow_id,
                        elapsed_seconds=time.monotonic() - started_at,
                        timeout_seconds=self._shutdown_timeout_sec,
                        error_type=type(exc).__name__,
                        reason=str(exc),
                    )
            # Always close the watchdog so monitor/source resources are released.
            self._watchdog.close()
            if shutdown_error is not None:
                raise shutdown_error
        self._close_sinks()
        self._emit_all(StreamStatus.HEALTHY, phase=RuntimePhase.STOPPED, comms=CommsStatus.STOPPED)

    def close(self) -> None:
        if self._phase not in (RuntimePhase.STOPPED, RuntimePhase.CLOSED):
            try:
                self.stop()
            except Exception:
                _log.error(
                    "stop during close failed — force-closing watchdog and sinks",
                    dataflow_id=self._manifest.dataflow_id,
                    phase=self._phase.value,
                    exc_info=True,
                )
                if self._watchdog is not None:
                    with suppress(Exception):
                        self._watchdog.close()
                self._close_sinks()
        self._close_sink_error_queue()
        self._close_source_error_queue()
        self._phase = RuntimePhase.CLOSED

    def _emit_shutdown_transcript(self, result: object, *, elapsed_seconds: float) -> None:
        """Print each parent-correlated shutdown action and one stream summary."""
        if not isinstance(result, Mapping):
            return
        stream_results = result.get("stream_results", ())
        if not isinstance(stream_results, (list, tuple)):
            return
        for stream_result in stream_results:
            if not isinstance(stream_result, Mapping):
                continue
            transcript = stream_result.get("transcript", ())
            for record in transcript:
                payload = {
                    "dataflow_id": self._manifest.dataflow_id,
                    "shutdown_id": record.shutdown_id,
                    "action_seq": record.action_seq,
                    "stream_index": record.stream_index,
                    "actor": record.actor,
                    "actor_pid": record.actor_pid,
                    "phase": record.phase.value,
                    "action": record.action,
                    "outcome": record.outcome.value,
                    "emitted_at_ns": record.emitted_at_ns,
                    "elapsed_ms": record.elapsed_ms,
                }
                for field in (
                    "sink_id",
                    "output_id",
                    "worker_exitcode",
                    "error_type",
                    "reason",
                ):
                    value = getattr(record, field, None)
                    if value is not None:
                        payload[field] = value
                _log.info("dataflow_shutdown_action", **payload)

            _log.info(
                "dataflow_shutdown_summary",
                dataflow_id=self._manifest.dataflow_id,
                shutdown_id=stream_result.get("shutdown_id"),
                stream_index=stream_result.get("stream_index"),
                terminal_phase=stream_result.get("terminal_phase"),
                ok=stream_result.get("ok") is True,
                forced_termination=stream_result.get("forced_termination") is True,
                worker_exitcode=stream_result.get("worker_exitcode"),
                action_count=len(transcript) if isinstance(transcript, (list, tuple)) else 0,
                missing_phases=stream_result.get("missing_phases", []),
                elapsed_ms=round(elapsed_seconds * 1000),
            )

    @staticmethod
    def _shutdown_failure_message(result: object) -> str:
        if not isinstance(result, Mapping):
            return "DataFlow graceful shutdown returned no acknowledgement result"
        details = []
        if result.get("error"):
            details.append(str(result["error"]))
        if result.get("terminal_phase"):
            details.append(f"terminal_phase={result['terminal_phase']}")
        missing = result.get("missing_phases")
        if missing:
            details.append("missing_phases=" + ",".join(str(item) for item in missing))
        if result.get("forced_termination"):
            details.append("forced_termination=true")
        stream_results = result.get("stream_results", ())
        if isinstance(stream_results, (list, tuple)):
            for stream_result in stream_results:
                if not isinstance(stream_result, Mapping):
                    continue
                stream_details = []
                if stream_result.get("terminal_phase"):
                    stream_details.append(f"terminal_phase={stream_result['terminal_phase']}")
                missing = stream_result.get("missing_phases")
                if missing:
                    stream_details.append("missing_phases=" + ",".join(str(item) for item in missing))
                if stream_result.get("forced_termination"):
                    stream_details.append("forced_termination=true")
                if stream_details:
                    stream_index = stream_result.get("stream_index", "?")
                    details.append(f"stream_index={stream_index}:" + ";".join(stream_details))
        return "DataFlow graceful shutdown failed" + (": " + "; ".join(details) if details else "")

    def _close_sink_error_queue(self) -> None:
        """Close the sink-error queue if open."""
        q = self._sink_error_queue
        self._sink_error_queue = None
        if q is None:
            return
        close = getattr(q, "close", None)
        if callable(close):
            with suppress(Exception):
                close()
        join_thread = getattr(q, "join_thread", None)
        if callable(join_thread):
            with suppress(Exception):
                join_thread()

    def _close_source_error_queue(self) -> None:
        """Close the source-status queue if open."""
        q = self._source_error_queue
        self._source_error_queue = None
        if q is None:
            return
        close = getattr(q, "close", None)
        if callable(close):
            with suppress(Exception):
                close()
        join_thread = getattr(q, "join_thread", None)
        if callable(join_thread):
            with suppress(Exception):
                join_thread()

    # -- stack construction -------------------------------------------------

    def _build_stack(self) -> None:
        if self._watchdog is not None:
            return

        (
            Watchdog,
            Pod8206HR,
            Pod8401HR,
            DataFlow,
            CSVSink,
            Preamp,
            PrimaryChannelMode,
            SecondaryChannelMode,
        ) = self._importer()
        network = []
        try:
            for device_flow in self._manifest.device_flows:
                device_type = self._device_type(device_flow)
                pod = self._build_pod(
                    device_type,
                    Pod8206HR,
                    Pod8401HR,
                    Preamp,
                    PrimaryChannelMode,
                    SecondaryChannelMode,
                    device_flow,
                )
                # Track immediately so rollback can close the port if sinks fail next.
                self._pods.append(pod)
                runtime_context = self._runtime_context(CSVSink, device_flow, device_type, pod)
                sinks = build_sinks(device_flow.sinks, pod, runtime_context)
                self._sinks.extend(sinks)
                network.append((pod, sinks))

            # Worker calls these; parent drains the queues into reports.
            self._sink_error_queue = self._sink_error_queue_factory()
            sink_error_sender = _SinkErrorSender(self._sink_error_queue)
            self._source_error_queue = self._source_error_queue_factory()
            source_error_sender = _SourceErrorSender(self._source_error_queue)

            self._flowgraph = DataFlow(
                network,
                on_sink_error=sink_error_sender,
                on_source_error=source_error_sender,
            )
            self._watchdog = Watchdog(
                flowgraph=self._flowgraph,
                failure_threshold=self._failure_threshold,
                max_heartbeat_age_sec=self._max_heartbeat_age_sec,
                first_packet_timeout_sec=self._first_packet_timeout_sec,
                recovery_policy=self._manifest.policy,
            )
        except BaseException:
            self._rollback_stack_construction()
            raise

    def _rollback_stack_construction(self) -> None:
        """Tear down pods/sinks/queues built before a failed stack setup."""
        self._watchdog = None
        self._flowgraph = None
        self._close_sink_error_queue()
        self._close_source_error_queue()

        for sink in reversed(self._sinks):
            close = getattr(sink, "close", None)
            if callable(close):
                with suppress(Exception):
                    close()
        self._sinks.clear()

        for pod in reversed(self._pods):
            close = getattr(pod, "close_port", None)
            if not callable(close):
                close = getattr(pod, "close", None)
            if callable(close):
                with suppress(Exception):
                    close()
        self._pods.clear()

    def _runtime_context(
        self,
        CSVSink: type,
        device_flow,
        device_type: DeviceType,
        pod: Any,
    ) -> RuntimeContext:
        """Build the per-device context passed into the sink factory."""
        return RuntimeContext(
            dataflow_id=self._manifest.dataflow_id,
            device_id=device_flow.device_id,
            schema_hash=self._manifest.hash,
            session_id=self._manifest.session_id,
            csv_sink_class=CSVSink,
            csv_fieldnames=tuple(self._csv_fieldnames(device_type, pod)),
            secret_resolver=resolve_secret_from_env,
            plot_transport=None,
            sink_delivery_outbox_factory=self._sink_delivery_outbox_factory,
        )

    def _build_csv_sink(
        self,
        CSVSink: type,
        device_flow,
        sink_config,
        device_type: DeviceType,
        pod: Any,
    ) -> Any:
        """Build one CSV sink via the shared factory (legacy CSV-only entry)."""
        if sink_config.type != SinkType.CSV:
            raise ValueError(
                f"unsupported Morelia sink type: {sink_config.type.value!r}"
            )
        runtime_context = self._runtime_context(CSVSink, device_flow, device_type, pod)
        return build_sink(sink_config, pod, runtime_context)

    def _build_pod(
        self,
        device_type: DeviceType,
        Pod8206HR: type,
        Pod8401HR: type,
        Preamp: type,
        PrimaryChannelMode: type,
        SecondaryChannelMode: type,
        device_flow,
    ) -> Any:
        if device_type is DeviceType.POD8206HR:
            return self._build_pod8206hr(Pod8206HR, device_flow)
        if device_type is DeviceType.POD8401HR:
            return self._build_pod8401hr(
                Pod8401HR,
                Preamp,
                PrimaryChannelMode,
                SecondaryChannelMode,
                device_flow,
            )
        raise ValueError(f"unsupported Morelia device type: {device_type.value!r}")

    @staticmethod
    def _build_pod8206hr(Pod8206HR: type, device_flow) -> Any:
        params = dict(device_flow.parameters)
        preamp_gain = params.pop("preamp_gain", params.pop("gain", 10))
        baudrate = params.pop("baudrate", 9600)
        device_name = params.pop("device_name", device_flow.name)
        use_d2xx = params.pop("use_d2xx", False)
        sample_rate = params.pop("sample_rate", None)

        pod = Pod8206HR(
            device_flow.port,
            preamp_gain,
            baudrate=baudrate,
            device_name=device_name,
            use_d2xx=use_d2xx,
            sample_rate=sample_rate,
        )
        for key, value in params.items():
            if not hasattr(pod, key):
                raise ValueError(f"unsupported Pod8206HR parameter: {key!r}")
            setattr(pod, key, value)
        return pod

    @staticmethod
    def _build_pod8401hr(
        Pod8401HR: type,
        Preamp: type,
        PrimaryChannelMode: type,
        SecondaryChannelMode: type,
        device_flow,
    ) -> Any:
        params = dict(device_flow.parameters)
        preamp = _enum_member(Preamp, params.pop("preamp"), "preamp")
        primary_values = params.pop("primary_channel_modes")
        primary_channel_modes = tuple(
            _enum_member(PrimaryChannelMode, value, "primary_channel_modes")
            for value in _required_four(primary_values, "primary_channel_modes")
        )
        secondary_values = params.pop("secondary_channel_modes")
        secondary_channel_modes = tuple(
            _enum_member(SecondaryChannelMode, value, "secondary_channel_modes")
            for value in _required_six(secondary_values, "secondary_channel_modes")
        )
        ss_gain = _optional_four(params.pop("ss_gain", (None, None, None, None)), "ss_gain")
        preamp_gain = _optional_four(
            params.pop("preamp_gain", (None, None, None, None)),
            "preamp_gain",
        )
        baudrate = params.pop("baudrate", 9600)
        device_name = params.pop("device_name", device_flow.name)
        use_d2xx = params.pop("use_d2xx", False)

        pod = Pod8401HR(
            device_flow.port,
            preamp,
            primary_channel_modes,
            secondary_channel_modes,
            ss_gain=ss_gain,
            preamp_gain=preamp_gain,
            baudrate=baudrate,
            device_name=device_name,
            use_d2xx=use_d2xx,
        )
        for key, value in params.items():
            if not hasattr(pod, key):
                raise ValueError(f"unsupported Pod8401HR parameter: {key!r}")
            setattr(pod, key, value)
        return pod

    @staticmethod
    def _device_type(device_flow) -> DeviceType:
        candidates = []
        if isinstance(device_flow.device_id, str):
            candidates.append(device_flow.device_id.split(":", 1)[0])
        if isinstance(device_flow.name, str):
            candidates.append(device_flow.name)

        for candidate in candidates:
            try:
                return DeviceType(candidate.lower())
            except ValueError:
                continue
        return DeviceType.POD8206HR

    @staticmethod
    def _csv_fieldnames(device_type: DeviceType, pod: Any) -> list[str]:
        if device_type is DeviceType.POD8206HR:
            return ["time", "EEG1", "EEG2", "EEG3/EMG", "TTL1", "TTL2", "TTL3", "TTL4"]
        if device_type is DeviceType.POD8401HR:
            channel_names = ("A", "B", "C", "D")
            mapper = getattr(type(pod), "get_channel_map_for_preamp_device", None)
            if callable(mapper) and getattr(pod, "preamp", None) is not None:
                channel_names = tuple(mapper(pod.preamp).values())
            return [
                "time",
                *channel_names,
                "aEXT0",
                "aEXT1",
                "aTTL1",
                "aTTL2",
                "aTTL3",
                "aTTL4",
            ]
        raise ValueError(f"unsupported Morelia device type: {device_type.value!r}")

    # -- reports ------------------------------------------------------------

    def _run_watchdog(self) -> None:
        # Daemon thread: log unexpected death so a stalled report feed is visible.
        assert self._watchdog is not None
        try:
            self._run_watchdog_loop()
        except Exception as exc:
            _log.error(
                "morelia watchdog thread died",
                dataflow_id=self._manifest.dataflow_id,
                error_type=type(exc).__name__,
                reason=str(exc),
            )
            raise

    def _run_watchdog_loop(self) -> None:
        self._watchdog.run(
            report_interval_sec=self._report_interval_sec,
            stream_interval=self._stream_interval_sec,
            timeout_sec=self._timeout_sec,
            on_result=self._emit_from_watchdog_report,
            verbose=True,
        )

    def _emit_from_watchdog_report(
        self,
        report: dict[str, Any],
        recovery_id: str | None = None,
    ) -> None:
        stream_reports = list(report.get("streams", []))
        devices = []
        for index, device_id in enumerate(self._device_ids):
            stream = stream_reports[index] if index < len(stream_reports) else {}
            devices.append(
                DeviceReport(
                    device_id=device_id,
                    stream_status=self._map_stream_status(stream.get("stream_health")),
                )
            )

        self._drain_source_errors()
        diagnostics = self._watchdog_diagnostics(stream_reports)
        self._log_watchdog_status(report, diagnostics)
        self._emit_report(
            phase=self._phase,
            comms=CommsStatus.CURRENT,
            devices=tuple(devices),
            recovery_id=recovery_id,
            diagnostics=diagnostics,
        )

    def _log_watchdog_status(
        self,
        report: dict[str, Any],
        diagnostics: dict[str, object],
    ) -> None:
        """Log a compact watchdog status line (and per-stream details)."""
        watchdog_status = _bounded_text(report.get("watchdog_status"), 80)
        _log.info(
            "watchdog status report",
            component="morelia_watchdog",
            dataflow_id=self._manifest.dataflow_id,
            phase=self._phase.value,
            sequence_number=self._sequence,
            watchdog_status=watchdog_status,
        )

        streams = diagnostics.get("streams")
        if not isinstance(streams, list):
            return
        for stream_index, stream in enumerate(streams):
            if not isinstance(stream, dict):
                continue
            health = stream.get("health")
            recovery = stream.get("recovery")
            recovery = recovery if isinstance(recovery, dict) else {}
            failure = stream.get("failure")
            failure = failure if isinstance(failure, dict) else {}
            heartbeat = stream.get("heartbeat")
            heartbeat = heartbeat if isinstance(heartbeat, dict) else {}
            worker = stream.get("worker")
            worker = worker if isinstance(worker, dict) else {}
            source_read = stream.get("source_read")
            source_read = source_read if isinstance(source_read, dict) else {}
            startup = stream.get("startup")
            startup = startup if isinstance(startup, dict) else {}

            log = _log.info if health == StreamStatus.HEALTHY.value else _log.warning
            log(
                "watchdog stream status",
                component="morelia_watchdog",
                dataflow_id=self._manifest.dataflow_id,
                phase=self._phase.value,
                sequence_number=self._sequence,
                stream_index=stream_index,
                device_id=stream.get("device_id"),
                stream_status=health,
                action=stream.get("action"),
                reason=(
                    stream.get("initiating_failure_reason")
                    or stream.get("failure_reason")
                    or heartbeat.get("reason")
                ),
                recovery_stage=recovery.get("status"),
                policy_mode=recovery.get("policy"),
                recovery_attempt=stream.get("consecutive_nonhealthy_ticks"),
                failure_count=failure.get("count"),
                failure_threshold=failure.get("threshold"),
                error_message=failure.get("last_error"),
                worker_status=worker.get("status"),
                heartbeat_status=heartbeat.get("status"),
                heartbeat_age_seconds=heartbeat.get("age_sec"),
                source_read_state=source_read.get("state"),
                source_read_error_type=source_read.get("exception_type"),
                source_read_error_message=source_read.get("message"),
                source_read_consecutive_failures=source_read.get("consecutive_failures"),
                first_packet_timeout_seconds=startup.get("timeout_sec"),
                first_packet_remaining_seconds=startup.get("remaining_sec"),
            )

    def _watchdog_diagnostics(self, stream_reports: list[object]) -> dict[str, object]:
        """Project Morelia stream reports into a small operator-facing payload."""
        streams: list[dict[str, object]] = []
        for index, device_id in enumerate(self._device_ids):
            raw = stream_reports[index] if index < len(stream_reports) else {}
            stream = raw if isinstance(raw, dict) else {}
            health = self._map_stream_status(stream.get("stream_health"))
            if health is StreamStatus.HEALTHY:
                self._nonhealthy_streak_by_device[device_id] = 0
            else:
                self._nonhealthy_streak_by_device[device_id] += 1

            signals = stream.get("signals")
            signals = signals if isinstance(signals, dict) else {}
            heartbeat = signals.get("heartbeat")
            heartbeat = heartbeat if isinstance(heartbeat, dict) else {}
            worker = signals.get("worker")
            worker = worker if isinstance(worker, dict) else {}
            failure = signals.get("failure")
            failure = failure if isinstance(failure, dict) else {}
            action = stream.get("action")
            action = action if isinstance(action, dict) else {}
            recovery_event = stream.get("recovery_event")
            recovery_event = recovery_event if isinstance(recovery_event, dict) else {}
            startup = signals.get("startup")
            startup = startup if isinstance(startup, dict) else {}
            streams.append(
                {
                    "device_id": device_id,
                    "health": health.value,
                    "summary": _bounded_text(stream.get("summary"), 320),
                    "rule": _bounded_text(stream.get("rule"), 120),
                    "failure_reason": _bounded_text(stream.get("failure_reason"), 320),
                    "initiating_failure_reason": _bounded_text(
                        stream.get("initiating_failure_reason"), 320
                    ),
                    "action": _bounded_text(action.get("taken"), 120),
                    "consecutive_nonhealthy_ticks": self._nonhealthy_streak_by_device[device_id],
                    "failure": {
                        "count": failure.get("count"),
                        "threshold": failure.get("threshold"),
                        "last_error": _bounded_text(failure.get("last_error"), 500),
                    },
                    "heartbeat": {
                        "status": _bounded_text(heartbeat.get("status"), 120),
                        "reason": _bounded_text(heartbeat.get("reason"), 320),
                        "age_sec": heartbeat.get("age_sec"),
                        "max_age_sec": heartbeat.get("max_age_sec"),
                        "packet_count": heartbeat.get("packet_count"),
                    },
                    "worker": {
                        "status": _bounded_text(worker.get("status"), 120),
                        "exitcode": worker.get("exitcode"),
                    },
                    "source_read": self._current_source_read(device_id),
                    "startup": {
                        "elapsed_sec": startup.get("elapsed_sec"),
                        "timeout_sec": startup.get("timeout_sec"),
                        "remaining_sec": startup.get("remaining_sec"),
                    },
                    "recovery": {
                        "status": _bounded_text(recovery_event.get("status"), 80),
                        "policy": _bounded_text(recovery_event.get("recovery_policy"), 80),
                    },
                }
            )
        return {
            "watchdog": {
                "failure_threshold": self._failure_threshold,
                "max_heartbeat_age_seconds": self._max_heartbeat_age_sec,
                "first_packet_timeout_seconds": self._first_packet_timeout_sec,
                "report_interval_seconds": self._report_interval_sec,
                "stream_interval_seconds": self._stream_interval_sec,
                "operation_timeout_seconds": self._timeout_sec,
            },
            "streams": streams,
        }

    def _emit_all(
        self,
        stream_status: StreamStatus,
        *,
        phase: RuntimePhase,
        comms: CommsStatus = CommsStatus.CURRENT,
    ) -> None:
        self._phase = phase
        self._emit_report(
            phase=phase,
            comms=comms,
            devices=tuple(
                DeviceReport(device_id=device_id, stream_status=stream_status)
                for device_id in self._device_ids
            ),
        )

    def _emit_report(
        self,
        *,
        phase: RuntimePhase,
        comms: CommsStatus,
        devices: tuple[DeviceReport, ...],
        recovery_id: str | None = None,
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        # Drain sink failures first; they attach on ``sinks``, not ``devices``.
        self._drain_sink_errors()
        self._on_report(
            RuntimeReport(
                dataflow_id=self._manifest.dataflow_id,
                phase=phase,
                comms=comms,
                devices=devices,
                sequence=self._sequence,
                recovery_id=recovery_id,
                diagnostics=diagnostics,
                sinks=tuple(self._sink_reports.values()),
            )
        )
        self._sequence += 1

    def _drain_sink_errors(self) -> None:
        """Apply pending sink-write failures into ``_sink_reports`` (non-blocking)."""
        q = self._sink_error_queue
        if q is None:
            return
        while True:
            try:
                event = q.get_nowait()
            except queue.Empty:
                break
            except (OSError, ValueError):
                # Queue already closed during teardown.
                break
            if not isinstance(event, Mapping):
                continue
            report = self._sink_report_from_event(event)
            self._sink_reports[(report.source_id, report.sink_id)] = report

    def _current_source_read(self, device_id: str) -> dict[str, object] | None:
        """Return this device's source-read status, clearing a stale degraded latch."""
        status = self._source_status_by_device.get(device_id)
        if status is None:
            return None
        if status.get("state") != "degraded":
            return status
        timestamp_ns = status.get("timestamp_ns")
        if not isinstance(timestamp_ns, int) or isinstance(timestamp_ns, bool):
            return status
        age_sec = (time.time_ns() - timestamp_ns) / 1_000_000_000
        if age_sec > get_config().SOURCE_STATUS_STALE_AFTER_SECONDS:
            self._source_status_by_device.pop(device_id, None)
            return None
        return status

    def _drain_source_errors(self) -> None:
        """Apply pending source-read events into ``_source_status_by_device``."""
        q = self._source_error_queue
        if q is None:
            return
        while True:
            try:
                event = q.get_nowait()
            except queue.Empty:
                break
            except (OSError, ValueError):
                break
            if not isinstance(event, Mapping):
                continue
            status = _normalize_source_status(event)
            source_port = status.get("source_port")
            device_id = (
                self._device_id_by_port.get(source_port.lower())
                if isinstance(source_port, str)
                else None
            )
            if device_id is None:
                source_id = status.get("source_id")
                if isinstance(source_id, str) and source_id in self._stream_by_device:
                    device_id = source_id
            if device_id is None:
                continue
            timestamp_ns = status.get("timestamp_ns")
            if (
                not isinstance(timestamp_ns, int)
                or isinstance(timestamp_ns, bool)
                or timestamp_ns < 0
            ):
                status["timestamp_ns"] = time.time_ns()
            # ``recovered``/``healthy`` clears the degraded latch; do not keep error fields.
            if status.get("state") in ("recovered", "healthy"):
                previous = self._source_status_by_device.pop(device_id, None)
                if previous is not None:
                    _log.info(
                        "source read recovered",
                        component="morelia_watchdog",
                        dataflow_id=self._manifest.dataflow_id,
                        device_id=device_id,
                        exception_type=previous.get("exception_type"),
                        failures_survived=status.get("consecutive_failures"),
                    )
                continue
            self._source_status_by_device[device_id] = status

    def _sink_report_from_event(self, event: Mapping[str, object]) -> SinkReport:
        """Build a bounded ``SinkReport`` from one normalized sink-error event."""
        source_raw = event.get("source_id")
        source_id = source_raw if isinstance(source_raw, str) and source_raw else "unknown-source"
        sink_raw = event.get("sink_id")
        sink_id = sink_raw if isinstance(sink_raw, str) and sink_raw else "unknown-sink"
        sink_class = _bounded_text(event.get("sink_class"), 120) or "unknown"

        state = event.get("state")
        if state == "degraded":
            health = SinkHealth.DEGRADED
            delivery = SinkDeliveryState.DEGRADED
        elif state in {"recovered", "healthy"}:
            health = SinkHealth.HEALTHY
            delivery = SinkDeliveryState.DELIVERED
        else:
            health = SinkHealth.FAILED
            delivery = SinkDeliveryState.FAILED

        identity = (source_id, sink_id)
        seq = self._sink_seq.get(identity, 0)
        self._sink_seq[identity] = seq + 1

        timestamp_ns = event.get("timestamp_ns")
        if not isinstance(timestamp_ns, int) or isinstance(timestamp_ns, bool) or timestamp_ns < 0:
            timestamp_ns = time.time_ns()

        last_success_seq = event.get("last_success_seq")
        if (
            not isinstance(last_success_seq, int)
            or isinstance(last_success_seq, bool)
            or last_success_seq < 0
        ):
            last_success_seq = None

        return SinkReport(
            sink_id=sink_id,
            source_id=source_id,
            sink_class=sink_class,
            health=health,
            delivery=delivery,
            sequence=seq,
            state_timestamp_ns=timestamp_ns,
            buffered_samples=_sink_counter(event.get("buffered_samples")),
            buffered_bytes=_sink_counter(event.get("buffered_bytes")),
            sample_loss=_sink_counter(event.get("sample_loss")),
            byte_loss=_sink_counter(event.get("byte_loss")),
            failure_kind=_sink_field(event.get("failure_kind"), 120),
            exception_type=_sink_field(event.get("exception_type"), 120),
            message=_sink_field(event.get("message"), 500),
            last_success_seq=last_success_seq,
        )

    @staticmethod
    def _map_stream_status(value: object) -> StreamStatus:
        if value == "healthy":
            return StreamStatus.HEALTHY
        if value == "unhealthy":
            return StreamStatus.UNHEALTHY
        return StreamStatus.SUSPECT

    def _require(self, *allowed: RuntimePhase) -> None:
        if self._phase not in allowed:
            allowed_names = ", ".join(phase.value for phase in allowed)
            raise RuntimeError(
                f"cannot do this from phase {self._phase.value!r}; expected one of: {allowed_names}"
            )

    @contextmanager
    def _hardware_boundary(self, step: str):
        """Log hardware-step failures, then re-raise unchanged."""
        try:
            yield
        except Exception as exc:
            _log.error(
                "morelia hardware step failed",
                dataflow_id=self._manifest.dataflow_id,
                action=step,
                error_type=type(exc).__name__,
                reason=str(exc),
            )
            raise

    def _close_sinks(self) -> None:
        for sink in self._sinks:
            close = getattr(sink, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as exc:
                    _log.warning(
                        "closing output sink failed — data may be unflushed",
                        dataflow_id=self._manifest.dataflow_id,
                        error=type(exc).__name__,
                        message=str(exc),
                    )


def _bounded_text(value: object, limit: int) -> str | None:
    """Truncate a string to ``limit``, or return ``None`` if not a str."""
    if not isinstance(value, str):
        return None
    return value[:limit]


def _required_four(value: object, key: str) -> tuple[object, object, object, object]:
    values = _optional_four(value, key)
    if any(item is None for item in values):
        raise ValueError(f"{key} must contain four non-null values")
    return values


def _required_six(
    value: object,
    key: str,
) -> tuple[object, object, object, object, object, object]:
    if not isinstance(value, (list, tuple)) or len(value) != 6:
        raise ValueError(f"{key} must be a 6-tuple")
    values = tuple(value)
    if any(item is None for item in values):
        raise ValueError(f"{key} must contain six non-null values")
    return values  # type: ignore[return-value]


def _optional_four(value: object, key: str) -> tuple[object, object, object, object]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"{key} must be a 4-tuple")
    return tuple(value)  # type: ignore[return-value]


def _enum_member(enum_type: type, value: object, key: str) -> Any:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, Enum):
        value = value.name
    if not isinstance(value, str):
        raise ValueError(f"{key} must be an enum member name")
    try:
        return getattr(enum_type, value)
    except AttributeError:
        try:
            return enum_type[value]
        except (KeyError, TypeError):
            raise ValueError(f"unknown {key} value: {value!r}") from None
