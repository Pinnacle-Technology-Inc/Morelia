"""Worker-side sink factory — the sole mapping from manifest type to adapter.

This module centralizes the construction of runtime sink adapters from the
resolved v2 ``SinkConfig`` descriptors carried by a manifest device flow. It is
the *only* place that decides, per :class:`~app.domain.enums.SinkType`, which
runtime adapter to build (gap SINK-04/SINK-13/SINK-21, design doc section 6
"Runtime construction and dependency preflight").

Design invariants
-----------------
* **Explicit ``match`` on ``SinkType``** — six cases do not justify dynamic
  class loading or arbitrary imports (design doc section 6). Each approved type
  has its own branch; there is no catch-all that "falls through" to CSV.
* **Worker-only handle ownership (SINK-21)** — the factory constructs
  *descriptors* only. For CSV it builds a deferred-open
  :class:`~app.output.managed_csv_sink.ManagedCsvSink` whose ``__init__`` opens
  nothing; the live handle is created later, worker-side, by ``open()``. The
  factory never opens a handle, so it is safe to run in the parent watchdog
  process during stack construction and recovery planning.
* **Lightweight import surface** — importing this module must not import Morelia,
  pyserial, a database, Flask, or any optional sink dependency. The concrete CSV
  sink class is *injected* via :class:`RuntimeContext` (``csv_sink_class``), and
  optional-dependency availability is *probed* with
  ``importlib.util.find_spec`` (bounded discovery; never executes a module body,
  so no native binary loads or sockets open here).
* **Manifest order and identity preserved** — :func:`build_sinks` builds one
  adapter per ``SinkConfig`` in order; each adapter carries the source's
  ``sink_id`` identity through to the descriptor.

Not-yet-implemented types (design doc section 6; SCOPE of packet 13)
--------------------------------------------------------------------
Only CSV is constructed today. EDF, PVFS, Influx, Quest, and Plot are approved
``SinkType`` values whose runtime adapters land in later packets (14/15/24/25/27).
Their branches produce a **typed, sink-addressed** outcome rather than a crash or
a silent CSV fallback:

* :class:`SinkDependencyMissing` — the optional/native dependency for that type
  is not importable on this platform (disables only *that* type, per packet 08).
* :class:`SinkTypeNotImplemented` — dependencies are present, but the managed
  runtime adapter has not been built yet.

Extension point / handoff (packets 14, 15, 24, 25, 27)
------------------------------------------------------
To register a new ``SinkType`` builder, replace that type's branch in
:func:`build_sink` (currently ``_build_unavailable``) with a dedicated
``_build_<type>`` that reads what it needs from :class:`RuntimeContext` — the
output/segment allocator (EDF/PVFS), the secret resolver (Influx/Quest), or the
plot transport (Plot) — and returns an adapter honoring the common lifecycle
(``open() -> write/flush -> get_dict() -> close()``; see ``ManagedCsvSink``).
The ``RuntimeContext`` fields and the typed error shapes below are frozen for
those packets.
"""

from __future__ import annotations

import importlib.util
import platform
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.domain.enums import SinkType

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.runtime_host.manifest import SinkConfig


__all__ = [
    "RuntimeContext",
    "SinkConstructionError",
    "SinkDependencyMissing",
    "SinkTypeNotImplemented",
    "build_sink",
    "build_sinks",
]


# ---------------------------------------------------------------------------
# Runtime context — the dependency-injection surface for sink construction.
#
# Frozen so a builder cannot mutate shared state mid-build. Today only the CSV
# fields are populated; the allocator / secret-resolver / plot-transport slots
# are the reserved injection points later packets fill in (design doc section 6:
# "runtime_context supplies dataflow ID, manifest hash, device ID,
# output/segment allocator, secret resolver, and plot transport").
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeContext:
    """Everything a sink builder may need that is not on the ``SinkConfig``.

    Scoped to one source (one ``pod``/device flow): ``device_id`` and the CSV
    ``csv_fieldnames`` are per-device. ``dataflow_id`` and ``schema_hash`` come
    from the manifest.
    """

    dataflow_id: str
    device_id: str
    schema_hash: str | None = None
    session_id: int | None = None

    # -- CSV (packet 12/13): worker-owned deferred-open sink -----------------
    # The concrete ManagedCsvSink class is injected (never imported here) so the
    # factory stays free of Flask/DB imports and the caller keeps ownership of
    # the Morelia import boundary. ``csv_fieldnames`` is the resolved header for
    # this device's packet schema.
    csv_sink_class: type | None = None
    csv_fieldnames: Sequence[str] | None = None

    # -- Reserved injection points for later packets -------------------------
    # allocator:       output/segment allocator for managed EDF/PVFS (14/15).
    # secret_resolver: resolves api_token_env in the worker boundary (24/25).
    # plot_transport:  browser plot channel (27).
    # delivery_outbox / sink_delivery_outbox_factory: the per-dataflow bounded
    #   SinkDeliveryOutbox for Influx/Quest outage buffer+replay (24/25 read
    #   these; the runtime-integration packet 26 populates them). Prefer the
    #   *factory* (a picklable path-based callable) over a live handle, since a
    #   SQLite outbox handle cannot cross into the DataFlow worker process.
    allocator: Any | None = None
    secret_resolver: Any | None = None
    plot_transport: Any | None = None
    delivery_outbox: Any | None = None
    sink_delivery_outbox_factory: Any | None = None

    # -- Recovery resume identity, keyed by sink_id (SINK-05/SINK-06) ---------
    # Empty on a first build — which is exactly what makes that build mint
    # component 0. Populated ONLY when a stream is being rebuilt after a
    # failure (runtime_child.morelia's reconstruction hook), where each file
    # sink must resume its EXISTING logical output instead of trying to create
    # a fresh component 0 over a path the previous segment's file still holds.
    # Without this the rebuilt descriptor carries output_id=None, and open()
    # takes managed_file.create() -> OutputFileAlreadyExistsError, which no
    # amount of retrying can clear.
    segment_resume: Mapping[str, Mapping[str, Any]] | None = None


# ---------------------------------------------------------------------------
# Typed construction outcomes — sink-addressed so one failed sink is
# identifiable even while sibling sinks on the same source are fine.
# ---------------------------------------------------------------------------


class SinkConstructionError(Exception):
    """A runtime sink adapter could not be constructed from its descriptor.

    Carries the offending ``sink_id`` and ``sink_type`` so a caller can name the
    exact sink (design doc section 6: "One failed sink must be identifiable").
    """

    def __init__(self, sink_id: str | None, sink_type: object, message: str) -> None:
        self.sink_id = sink_id
        self.sink_type = sink_type
        super().__init__(message)


class SinkTypeNotImplemented(SinkConstructionError):
    """The sink type is approved but its runtime adapter is not built yet.

    Distinct from :class:`SinkDependencyMissing`: the dependencies are present;
    only the managed adapter is missing (it lands in a later packet).
    """

    def __init__(self, sink_id: str | None, sink_type: SinkType) -> None:
        super().__init__(
            sink_id,
            sink_type,
            f"sink {sink_id!r} of type {sink_type.value!r} is not yet available: "
            "its managed runtime adapter has not been implemented in this build",
        )


class SinkDependencyMissing(SinkConstructionError):
    """A required optional/native dependency for this sink type is unavailable.

    Disables only this sink type (packet 08), never a broad failure. ``reason``
    explains the gap (missing import or unsupported platform) and ``extra`` names
    the pip extra that installs it, if any.
    """

    def __init__(
        self,
        sink_id: str | None,
        sink_type: SinkType,
        *,
        reason: str,
        extra: str | None = None,
    ) -> None:
        self.reason = reason
        self.extra = extra
        remediation = f"; install the {extra!r} extra" if extra else ""
        super().__init__(
            sink_id,
            sink_type,
            f"sink {sink_id!r} of type {sink_type.value!r} is unavailable: "
            f"{reason}{remediation}",
        )


# ---------------------------------------------------------------------------
# Optional-dependency metadata (packet 08 import-name map). Kept local so the
# factory does not import the CLI ``doctor`` diagnostic (which pulls in click /
# Flask / SQLAlchemy). Import *names* are probed, never pip distribution names.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Dependency:
    imports: tuple[str, ...]
    extra: str | None
    platforms: tuple[str, ...] | None  # None = every platform


_DEPENDENCIES: dict[SinkType, _Dependency] = {
    SinkType.CSV: _Dependency(imports=(), extra=None, platforms=None),
    SinkType.EDF: _Dependency(imports=("pyedflib", "numpy"), extra="edf", platforms=None),
    SinkType.PVFS: _Dependency(
        imports=("pvfs_tools",), extra="pvfs", platforms=("Windows", "Linux")
    ),
    SinkType.INFLUX: _Dependency(
        imports=("influxdb_client", "reactivex"), extra="influx", platforms=None
    ),
    SinkType.QUEST: _Dependency(imports=("questdb", "reactivex"), extra="quest", platforms=None),
    SinkType.PLOT: _Dependency(imports=(), extra=None, platforms=None),
}


def _probe_import(name: str) -> bool:
    """Report whether *name* is importable without executing its module body.

    ``find_spec`` performs bounded discovery only, so probing e.g. ``pvfs_tools``
    cannot load its native binary or otherwise cause a side effect.
    """
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _require_dependencies(sink_config: SinkConfig) -> None:
    """Raise :class:`SinkDependencyMissing` if this type's deps are unavailable.

    Platform gate first (a native library on the wrong OS is a constraint, not a
    missing install), then the import-name probe.
    """
    sink_type = sink_config.type
    dependency = _DEPENDENCIES[sink_type]

    if dependency.platforms is not None and platform.system() not in dependency.platforms:
        allowed = " or ".join(dependency.platforms)
        raise SinkDependencyMissing(
            sink_config.sink_id,
            sink_type,
            reason=(
                f"native library requires {allowed}; "
                f"current platform is {platform.system()!r}"
            ),
            extra=dependency.extra,
        )

    missing = [name for name in dependency.imports if not _probe_import(name)]
    if missing:
        plural = "s" if len(missing) > 1 else ""
        raise SinkDependencyMissing(
            sink_config.sink_id,
            sink_type,
            reason=f"missing import{plural}: {', '.join(missing)}",
            extra=dependency.extra,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_sink(sink_config: SinkConfig, pod: Any, runtime_context: RuntimeContext) -> Any:
    """Construct one runtime sink adapter from a resolved ``SinkConfig``.

    Explicit ``match`` on the sink type — the sole type→adapter mapping. Returns
    a lifecycle-compatible adapter (``open`` / ``write_row`` / ``flush`` /
    ``get_dict`` / ``close``). Raises :class:`SinkConstructionError` (or a
    subclass) for a type whose adapter is unavailable, and never falls through to
    a different type.
    """
    sink_type = getattr(sink_config, "type", None)
    match sink_type:
        case SinkType.CSV:
            return _build_csv(sink_config, pod, runtime_context)
        case SinkType.EDF:
            return _build_edf(sink_config, pod, runtime_context)
        case SinkType.PVFS:
            return _build_pvfs(sink_config, pod, runtime_context)
        case SinkType.INFLUX:
            return _build_influx(sink_config, pod, runtime_context)
        case SinkType.QUEST:
            return _build_quest(sink_config, pod, runtime_context)
        case SinkType.PLOT:
            return _build_plot(sink_config, pod, runtime_context)
        case _:
            # Not a known SinkType at all — an unknown/corrupt descriptor.
            raise SinkConstructionError(
                getattr(sink_config, "sink_id", None),
                sink_type,
                f"unknown sink descriptor type: {sink_type!r}",
            )


def build_sinks(
    sink_configs: Sequence[SinkConfig],
    pod: Any,
    runtime_context: RuntimeContext,
) -> list[Any]:
    """Build one adapter per descriptor, in manifest order.

    On any construction failure (unknown descriptor or a builder raising), every
    already-created sibling adapter is closed in reverse creation order before
    the original failure propagates. Cleanup failures do not mask the original
    cause: they are attached to it as ``sink_cleanup_failures`` secondary
    diagnostics (design doc: "retain the first failure as cause, and report
    cleanup failures as secondary diagnostics").
    """
    built: list[Any] = []
    for sink_config in sink_configs:
        try:
            built.append(build_sink(sink_config, pod, runtime_context))
        except Exception as exc:
            cleanup_failures = _close_reverse(built)
            if cleanup_failures:
                with suppress(Exception):
                    exc.sink_cleanup_failures = cleanup_failures  # type: ignore[attr-defined]
            raise
    return built


# ---------------------------------------------------------------------------
# Per-type builders
# ---------------------------------------------------------------------------


def _resume_for(sink_config: SinkConfig, ctx: RuntimeContext) -> Mapping[str, Any]:
    """This sink's resume identity, or an empty mapping on a first build.

    Returning ``{}`` rather than ``None`` lets every builder spread it
    unconditionally, so the first-build path stays literally unchanged (no
    resume keys passed at all) while a rebuild carries the segment identity.
    """
    resume = (ctx.segment_resume or {}).get(sink_config.sink_id)
    return resume or {}


def _segment_kwargs(sink_config: SinkConfig, ctx: RuntimeContext) -> dict[str, Any]:
    """Resume kwargs for a segmenting sink (EDF/PVFS): full component identity."""
    resume = _resume_for(sink_config, ctx)
    if not resume:
        return {}
    return {
        "output_id": resume.get("output_id"),
        "logical_sink_id": resume.get("logical_sink_id"),
        "segment_index": resume.get("segment_index", 0),
    }


def _build_csv(sink_config: SinkConfig, pod: Any, ctx: RuntimeContext) -> Any:
    """Construct a deferred-open managed CSV sink descriptor (SINK-21).

    Preserves packet-12 output semantics exactly: only a descriptor is built
    here (no file, ``output_files`` row, DB handle, or writer). The concrete
    sink class is injected via ``ctx.csv_sink_class`` so this module imports no
    Flask/DB code.
    """
    csv_sink_class = ctx.csv_sink_class
    if csv_sink_class is None:
        raise SinkConstructionError(
            sink_config.sink_id,
            SinkType.CSV,
            "runtime context has no csv_sink_class to build a CSV sink",
        )
    if ctx.csv_fieldnames is None:
        raise SinkConstructionError(
            sink_config.sink_id,
            SinkType.CSV,
            "runtime context has no csv_fieldnames to build a CSV sink",
        )

    file_path = sink_config.parameters.get("file_path")
    if not file_path:
        raise ValueError(f"CSV sink {sink_config.sink_id!r} has no resolved file_path")

    # CSV resumes by reopening its one file in append mode (no second header),
    # so it takes output_id alone — it has no component chain to extend.
    resume = _resume_for(sink_config, ctx)
    return csv_sink_class(
        path=file_path,
        dataflow_id=ctx.dataflow_id,
        fieldnames=list(ctx.csv_fieldnames),
        device_id=ctx.device_id,
        sink_id=sink_config.sink_id,
        schema_hash=ctx.schema_hash,
        pod=pod,
        **({"output_id": resume["output_id"]} if resume.get("output_id") else {}),
    )


def _build_edf(sink_config: SinkConfig, pod: Any, ctx: RuntimeContext) -> Any:
    """Construct a deferred-open managed EDF sink descriptor (SINK-05/SINK-21).

    Descriptor only: like CSV, no file, ``output_files`` row, EDF writer, or
    native ``pyedflib`` handle is created here (the worker's ``open()`` allocates
    an exclusive segment and constructs the writer). Channels and the sample rate
    are left unresolved so they are derived from ``pod`` worker-side, keeping this
    factory free of a Morelia device import.

    ``ManagedEdfSink`` is imported lazily so the module-level import surface of
    this factory stays lightweight (no ``pyedflib``/Flask/DB at import time); the
    packet-08 dependency probe already ran via :func:`_require_dependencies`, so
    reaching here means ``pyedflib``/``numpy`` are importable.
    """
    _require_dependencies(sink_config)

    file_path = sink_config.parameters.get("file_path")
    if not file_path:
        raise ValueError(f"EDF sink {sink_config.sink_id!r} has no resolved file_path")

    from app.output.managed_edf_sink import ManagedEdfSink

    return ManagedEdfSink(
        path=file_path,
        dataflow_id=ctx.dataflow_id,
        device_id=ctx.device_id,
        sink_id=sink_config.sink_id,
        schema_hash=ctx.schema_hash,
        session_id=ctx.session_id,
        pod=pod,
        observe_on_scheduler=sink_config.parameters.get("observe_on_scheduler"),
        **_segment_kwargs(sink_config, ctx),
    )


def _build_pvfs(sink_config: SinkConfig, pod: Any, ctx: RuntimeContext) -> Any:
    """Construct a deferred-open managed PVFS sink descriptor (SINK-06/SINK-21).

    Descriptor only: like CSV/EDF, no container, ``output_files`` row, or native
    ``pvfs_tools`` handle is created here (the worker's ``open()`` allocates an
    exclusive segment and creates the container over the provably-empty claimed
    path). Channels/units/sample-rate are left unresolved so they are derived from
    ``pod`` worker-side, keeping this factory free of a Morelia device import.

    ``ManagedPvfsSink`` is imported lazily so this factory's module-level import
    surface stays lightweight (no ``pvfs_tools``/Flask/DB at import time); the
    packet-08 dependency probe already ran via :func:`_require_dependencies`
    (import name ``pvfs_tools``; native, Windows/Linux only), so reaching here
    means the native library is importable on this platform.
    """
    _require_dependencies(sink_config)

    file_path = sink_config.parameters.get("file_path")
    if not file_path:
        raise ValueError(f"PVFS sink {sink_config.sink_id!r} has no resolved file_path")

    from app.output.managed_pvfs_sink import ManagedPvfsSink

    return ManagedPvfsSink(
        path=file_path,
        dataflow_id=ctx.dataflow_id,
        device_id=ctx.device_id,
        sink_id=sink_config.sink_id,
        schema_hash=ctx.schema_hash,
        session_id=ctx.session_id,
        pod=pod,
        observe_on_scheduler=sink_config.parameters.get("observe_on_scheduler"),
        # Enforce the invariant at the runtime boundary as defense in depth for
        # legacy or externally supplied manifests. Segment identity remains
        # controlled independently by _segment_kwargs.
        use_writer_process=True,
        device_preferences=sink_config.parameters.get("device_preferences"),
        **_segment_kwargs(sink_config, ctx),
    )


def _build_influx(sink_config: SinkConfig, pod: Any, ctx: RuntimeContext) -> Any:
    """Construct a deferred-open managed Influx sink descriptor (SINK-07/SINK-27).

    Descriptor only: like the other managed sinks, ``__init__`` opens no socket,
    imports no ``influxdb_client``, and resolves no credential — so it is safe to
    build in the parent watchdog. The worker's ``open()`` resolves ``api_token_env``
    (never the token value) through ``ctx.secret_resolver`` immediately before
    constructing the client, enforces initial availability, and drains the bounded
    delivery outbox on reconnect.

    The credential crosses into the worker only as the environment-variable *name*
    carried in ``parameters["api_token_env"]`` (packet 01 makes it required and
    rejects any literal token). ``ctx.secret_resolver`` is the worker-boundary hook
    ``Callable[[str], str | None]`` that maps that name to the token; when ``None``
    the adapter falls back to ``os.environ.get`` worker-side. The per-dataflow
    :class:`~app.watchdog_process.sink_delivery_outbox.SinkDeliveryOutbox` is
    injected at the worker boundary (packet 26) via optional ``ctx`` hooks; absent
    those, the descriptor still builds and only ``open()`` requires the outbox.

    ``ManagedInfluxSink`` is imported lazily so this factory's module-level import
    surface stays lightweight; the packet-08 dependency probe already ran via
    :func:`_require_dependencies` (import names ``influxdb_client``/``reactivex``),
    so reaching here means both are importable.
    """
    _require_dependencies(sink_config)

    from app.output.influx_sink import ManagedInfluxSink

    params = sink_config.parameters
    api_token_env = params.get("api_token_env")
    if not api_token_env:
        # Registry (packet 01) makes this required; guard defensively so a
        # malformed descriptor is a sink-addressed construction error, not a
        # deep AttributeError. The token VALUE is never referenced here.
        raise SinkConstructionError(
            sink_config.sink_id,
            SinkType.INFLUX,
            f"Influx sink {sink_config.sink_id!r} is missing required 'api_token_env'",
        )

    return ManagedInfluxSink(
        api_token_env=str(api_token_env),
        dataflow_id=ctx.dataflow_id,
        device_id=ctx.device_id,
        sink_id=sink_config.sink_id,
        acquisition_id=ctx.dataflow_id,
        schema_hash=ctx.schema_hash,
        session_id=ctx.session_id,
        url=params.get("url", "http://localhost:8086"),
        org=params.get("org", "default-org"),
        bucket=params.get("bucket", "influx_dump"),
        measurement=params.get("measurement", "default-measurement"),
        observe_on_scheduler=params.get("observe_on_scheduler"),
        buffer_max_age_seconds=params.get("buffer_max_age_seconds"),
        buffer_max_bytes=params.get("buffer_max_bytes"),
        pod=pod,
        secret_resolver=ctx.secret_resolver,
        # Worker-boundary delivery-outbox wiring is optional today (packet 26);
        # read it defensively so no new RuntimeContext field is required now.
        delivery_outbox=getattr(ctx, "delivery_outbox", None),
        outbox_factory=getattr(ctx, "sink_delivery_outbox_factory", None),
    )


def _build_quest(sink_config: SinkConfig, pod: Any, ctx: RuntimeContext) -> Any:
    """Construct a deferred-open managed Quest sink descriptor (SINK-08/SINK-27).

    Descriptor only: like the other managed service sinks, ``__init__`` opens no
    connection and imports no Quest client — so it is safe to build in the parent
    watchdog. The worker's ``open()`` constructs the QuestDB ILP client, enforces
    initial reachability (fail-start), and drains the bounded delivery outbox on
    reconnect.

    Quest uses the official QuestDB client in acknowledged ILP/HTTP mode and has
    no credential/token, so no secret is threaded here (contrast ``_build_influx``).
    Parameters (``host``, ``port``, ``measurement``, ``observe_on_scheduler``,
    ``buffer_max_age_seconds``, ``buffer_max_bytes``) are all optional; defaults
    come from Morelia's ``QuestSink``. The per-dataflow
    :class:`~app.watchdog_process.sink_delivery_outbox.SinkDeliveryOutbox` is
    injected at the worker boundary (packet 26) via optional ``ctx`` hooks; absent
    those, the descriptor still builds and only ``open()`` requires the outbox.

    ``ManagedQuestSink`` is imported lazily so this factory's module-level import
    surface stays lightweight; the packet-08 dependency probe already ran via
    :func:`_require_dependencies` (import name ``reactivex``), so reaching here
    means it is importable.
    """
    _require_dependencies(sink_config)

    from app.output.quest_sink import ManagedQuestSink

    params = sink_config.parameters

    return ManagedQuestSink(
        dataflow_id=ctx.dataflow_id,
        device_id=ctx.device_id,
        sink_id=sink_config.sink_id,
        acquisition_id=ctx.dataflow_id,
        schema_hash=ctx.schema_hash,
        session_id=ctx.session_id,
        host=params.get("host", "localhost"),
        port=params.get("port", 9000),
        measurement=params.get("measurement", "default_measurement"),
        observe_on_scheduler=params.get("observe_on_scheduler"),
        buffer_max_age_seconds=params.get("buffer_max_age_seconds"),
        buffer_max_bytes=params.get("buffer_max_bytes"),
        pod=pod,
        # Worker-boundary delivery-outbox wiring is optional today (packet 26);
        # read it defensively so no new RuntimeContext field is required now.
        delivery_outbox=getattr(ctx, "delivery_outbox", None),
        outbox_factory=getattr(ctx, "sink_delivery_outbox_factory", None),
    )


def _build_plot(sink_config: SinkConfig, pod: Any, ctx: RuntimeContext) -> Any:
    """Construct a deferred-open managed Plot sink descriptor (SINK-09/SINK-21).

    Descriptor only: like the other managed sinks, ``__init__`` connects no
    transport and starts no thread, so the parent watchdog can build/rebuild it
    safely. Plot needs *no* optional/native dependency (its consumer is a browser
    over an authenticated SSE channel, not a native library, per packet 08), so
    there is no :func:`_require_dependencies` probe and this branch never raises
    :class:`SinkTypeNotImplemented`.

    The live browser transport is resolved **worker-side** at ``open()``. Because
    ``morelia.py`` currently leaves ``RuntimeContext.plot_transport`` as ``None``
    (packet 26) and is outside this packet's edit set, both the live handle and an
    optional picklable ``plot_transport_factory`` are read *defensively* via
    ``getattr`` — the descriptor still builds when both are absent (the sink then
    runs in bounded no-consumer/drop mode), and the parent can later wire a live
    transport (or a picklable factory) through ``RuntimeContext`` with no change
    here.

    ``ManagedPlotSink`` is imported lazily so this factory's module-level import
    surface stays lightweight (no Flask/broker import at import time).
    """
    from app.output.plot_sink import ManagedPlotSink

    params = sink_config.parameters
    return ManagedPlotSink(
        dataflow_id=ctx.dataflow_id,
        device_id=ctx.device_id,
        sink_id=sink_config.sink_id,
        session_id=ctx.session_id,
        schema_hash=ctx.schema_hash,
        chunk_samples=params.get("chunk_samples"),
        max_display_rate=params.get("max_display_rate"),
        channel_names=params.get("channel_names"),
        observe_on_scheduler=params.get("observe_on_scheduler"),
        pod=pod,
        # Worker-boundary plot-transport wiring is optional today (packet 26 left
        # plot_transport=None; morelia.py is out of this packet's edit set). Read
        # both the live handle and an optional picklable factory defensively so no
        # new RuntimeContext field is required now.
        transport=getattr(ctx, "plot_transport", None),
        transport_factory=getattr(ctx, "plot_transport_factory", None),
    )


def _build_unavailable(sink_config: SinkConfig) -> Any:
    """Typed outcome for an approved type whose adapter is not built yet.

    Reports a missing dependency first (more actionable), otherwise reports the
    adapter as not-yet-implemented. This is the branch a later packet replaces
    with a real ``_build_<type>`` builder.
    """
    _require_dependencies(sink_config)
    raise SinkTypeNotImplemented(sink_config.sink_id, sink_config.type)


def _close_reverse(sinks: list[Any]) -> list[tuple[Any, Exception]]:
    """Close created adapters in reverse order; collect (not raise) failures."""
    failures: list[tuple[Any, Exception]] = []
    for sink in reversed(sinks):
        close = getattr(sink, "close", None)
        if not callable(close):
            continue
        try:
            close()
        except Exception as exc:  # noqa: BLE001 - cleanup is best-effort, reported not raised
            failures.append((sink, exc))
    return failures
