"""Device discovery service and providers."""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import Event, RLock, Thread
from typing import Protocol
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from app.discovery.pod_scan import DiscoveredDevice, PodProber, detect_pod_devices
from app.domain.enums import DeviceClaimState, DeviceType
from app.repositories.device_configs import DeviceConfigRepository
from app.repositories.device_seen import DeviceSeenRepository

logger = logging.getLogger(__name__)

AVAILABILITY_VALUES = frozenset({"available", "unavailable", "unopenable", "not_found"})
PortLister = Callable[[], Iterable[object]]
ConfiguredDeviceTypesProvider = Callable[[], Mapping[str, DeviceType]]


class DiscoveryProvider(Protocol):
    """Short-lived device discovery provider."""

    def scan(self) -> list[DiscoveredDevice]:
        """Return discovered device rows without retaining hardware handles."""


@dataclass(frozen=True, slots=True)
class ScanResult:
    scan_id: str
    scanned_at: datetime
    devices: list[DiscoveredDevice]
    warnings: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ScanSnapshot(ScanResult):
    state: str = "enumerating"
    revision: int = 0
    completed: int = 0
    total: int = 0
    finished_at: datetime | None = None
    error: str | None = None


class _ScanJob:
    def __init__(self):
        self.snapshot = ScanSnapshot(uuid4().hex, datetime.now(UTC), [])
        self.done = Event()
        self.error: Exception | None = None


class FakeDiscoveryProvider:
    """Deterministic discovery provider for tests and local CI."""

    def __init__(self, devices: Iterable[DiscoveredDevice] | None = None) -> None:
        self._devices = list(devices) if devices is not None else [_fake_pod()]

    def scan(self) -> list[DiscoveredDevice]:
        return list(self._devices)


class SerialPodProvider:
    """USB-serial POD discovery provider.

    This is one provider for the transport. Per-model differentiation belongs in
    POD identification and the config registry, not in separate provider classes.
    """

    def __init__(
        self,
        *,
        port_lister: PortLister | None = None,
        prober: PodProber | None = None,
    ) -> None:
        self._port_lister = port_lister or _live_port_lister
        self._prober = prober

    def scan(self) -> list[DiscoveredDevice]:
        return detect_pod_devices(port_lister=self._port_lister, prober=self._prober)


class DeviceDiscoveryService:
    def __init__(
        self,
        provider: DiscoveryProvider,
        configured_device_types: ConfiguredDeviceTypesProvider | None = None,
        device_seen_repository: DeviceSeenRepository | None = None,
        context_factory: Callable = nullcontext,
    ) -> None:
        self._provider = provider
        self._configured_device_types = configured_device_types
        self._device_seen_repository = device_seen_repository or DeviceSeenRepository()
        self._context_factory = context_factory
        self._lock = RLock()
        self._jobs: OrderedDict[str, _ScanJob] = OrderedDict()
        self._active: _ScanJob | None = None

    def _join_or_create(self) -> tuple[_ScanJob, bool]:
        with self._lock:
            if self._active is not None and not self._active.done.is_set():
                return self._active, False
            job = _ScanJob()  # Identity and start time exist before enumeration.
            self._active = job
            self._jobs[job.snapshot.scan_id] = job
            while len(self._jobs) > 8:
                self._jobs.popitem(last=False)
            return job, True

    def start(self) -> ScanSnapshot:
        """Start or join the app's scan; callers never own probe lifetimes."""
        job, created = self._join_or_create()
        if created:
            try:
                Thread(target=self._run, args=(job,), name="device-scan", daemon=True).start()
            except Exception as exc:
                with self._lock:
                    self._mark_job_failed(job, exc)
                    job.done.set()
                raise
        with self._lock:
            return deepcopy(job.snapshot)

    def snapshot(self, scan_id: str) -> ScanSnapshot:
        """Read retained progress without starting any hardware work."""
        with self._lock:
            return deepcopy(self._jobs[scan_id].snapshot)

    def scan(self) -> ScanResult:
        """Compatibility API: wait for the same job used by progressive callers."""
        job, created = self._join_or_create()
        if created:
            self._run(job)
        else:
            job.done.wait()
        if job.error is not None:
            raise job.error
        with self._lock:
            result = deepcopy(job.snapshot)
        return ScanResult(result.scan_id, result.scanned_at, result.devices, result.warnings)

    def _run(self, job: _ScanJob) -> None:
        try:
            # Flask/SQLAlchemy context belongs to this coordinator, never probes.
            with self._context_factory():
                configured_types = self._configured_device_types() if self._configured_device_types else {}

                def progress(update):
                    devices = _apply_configured_device_types(update.devices, configured_types)
                    with self._lock:
                        job.snapshot = replace(
                            job.snapshot, devices=deepcopy(devices), warnings=deepcopy(update.warnings),
                            state="probing", revision=job.snapshot.revision + 1,
                            completed=update.completed, total=update.total,
                        )

                progressive_scan = getattr(self._provider, "scan_progress", None)
                if callable(progressive_scan):
                    devices, warnings = progressive_scan(on_progress=progress)
                else:
                    devices = self._provider.scan()
                    warnings = getattr(self._provider, "warnings", ())
                devices = _apply_configured_device_types(devices, configured_types)
                self._record_scan(job.snapshot.scan_id, devices)
                with self._lock:
                    total = max(job.snapshot.total, len(devices))
                    job.snapshot = replace(
                        job.snapshot, devices=deepcopy(devices), warnings=deepcopy(tuple(warnings)),
                        state="complete", revision=job.snapshot.revision + 1,
                        completed=total, total=total, finished_at=datetime.now(UTC),
                    )
        except Exception as exc:
            logger.exception("Device scan failed")
            with self._lock:
                self._mark_job_failed(job, exc)
        finally:
            # A new job cannot begin before every worker has completed cleanup.
            with self._lock:
                job.done.set()

    def _mark_job_failed(self, job: _ScanJob, error: Exception) -> None:
        """Publish the failure while the caller holds the service lock."""
        job.error = error
        job.snapshot = replace(
            job.snapshot, state="failed", error=str(error),
            revision=job.snapshot.revision + 1, finished_at=datetime.now(UTC),
        )

    def _record_scan(self, scan_id: str, devices: list[DiscoveredDevice]) -> None:
        """Persist discovery evidence. Never blocks or fails a scan.

        Device List rendering is read-first and must not depend on this write
        succeeding, so a database problem here is logged and swallowed exactly
        like ``configured_device_types_from_db`` does elsewhere in this module.
        """
        try:
            self._device_seen_repository.record_scan(scan_id, devices)
        except (RuntimeError, SQLAlchemyError):
            logger.warning(
                "Skipping device_seen persistence because the database is unavailable.",
                exc_info=True,
            )


def _live_port_lister() -> Iterable[object]:
    from serial.tools.list_ports import comports

    return comports()


class FtdiPodProvider(SerialPodProvider):
    """Production discovery of physical FTDI devices over VCP and native D2XX."""

    def __init__(
        self, *, directory, port_lister=None, native_lister=None, prober=None, configurations=None,
        max_workers=4,
    ) -> None:
        super().__init__(port_lister=port_lister)
        self._directory = directory
        self._native_lister = native_lister
        self._endpoint_prober = prober
        self._configurations = configurations or configured_connections_from_db
        self._max_workers = max_workers
        self.warnings: tuple[dict[str, str], ...] = ()

    def scan(self) -> list[DiscoveredDevice]:
        devices, self.warnings = self.scan_progress()
        return devices

    def scan_progress(self, *, on_progress=None):
        from app.discovery.native_scan import scan_endpoints

        configured, claimed = self._configurations()
        kwargs = {}
        if self._native_lister is not None:
            kwargs["native_lister"] = self._native_lister
        if self._endpoint_prober is not None:
            kwargs["prober"] = self._endpoint_prober
        return scan_endpoints(
            port_lister=self._port_lister,
            directory=self._directory,
            configured=configured,
            claimed=claimed,
            max_workers=self._max_workers,
            on_progress=on_progress,
            **kwargs,
        )


def configured_connections_from_db() -> tuple[dict[str, dict], frozenset[str]]:
    """Read profiles and claims before probing; claimed identities are never opened."""
    rows = DeviceConfigRepository().list()
    configured: dict[str, dict] = {}
    claimed: set[str] = set()
    for row in rows:
        connection = dict(getattr(row, "connection", None) or {})
        if row.hardware_id in configured and configured[row.hardware_id] != connection:
            # Conflicting model records cannot safely choose a physical probe profile.
            claimed.add(row.hardware_id)
        configured[row.hardware_id] = connection
        if DeviceClaimState(row.claim_state) is not DeviceClaimState.FREE:
            claimed.add(row.hardware_id)
    return configured, frozenset(claimed)


def _fake_pod() -> DiscoveredDevice:
    return DiscoveredDevice(
        type=DeviceType.POD8206HR,
        port="FAKE-POD-8206HR",
        # Must satisfy the hardware_id contract (1-8 ASCII alphanumerics) or the fake pod
        # cannot be registered from the Device List like a real one.
        hardware_id="99999999",
        label="Fake POD 8206HR",
        availability="available",
    )


def configured_device_types_from_db() -> dict[str, DeviceType]:
    """Map registered FTDI serial numbers to persisted physical device types."""
    try:
        return DeviceConfigRepository().device_type_by_hardware_id()
    except SQLAlchemyError:
        logger.info(
            "Skipping device-config discovery enrichment because the database is unavailable.",
            exc_info=True,
        )
        return {}


def _apply_configured_device_types(
    devices: list[DiscoveredDevice],
    configured_types: Mapping[str, DeviceType],
) -> list[DiscoveredDevice]:
    enriched = []
    for device in devices:
        configured_type = (
            configured_types.get(device.hardware_id)
            if device.type is DeviceType.UNKNOWN
            and device.availability in ("unopenable", "unavailable", "unverified")
            and device.hardware_id
            else None
        )
        if configured_type is None:
            enriched.append(device)
            continue

        enriched.append(replace(device, type=configured_type))
    return enriched
