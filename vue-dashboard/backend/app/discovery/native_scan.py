"""Discover PODs over VCP and D2XX while holding a device lease during each probe."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from threading import RLock

from app.discovery.ftdi_transport import NativeHandleCleanupError
from app.discovery.pod_scan import (
    TYPE_MAP,
    DiscoveredDevice,
    PodProbe,
    _attribute,
    _cleanup_pod,
    _import_probe_class,
    _is_probe_candidate,
    _label,
    _payload_value,
    _port_name,
)
from app.discovery.windows_ftdi_identity import annotate_endpoints
from app.domain.connections import normalize_connection
from app.domain.enums import DeviceType
from app.services.connections import list_native_endpoints
from app.watchdog_process.hardware_lease import HardwareLeaseBusy, HardwareLeaseSet

logger = logging.getLogger(__name__)
_cleanup_leases = {}
_cleanup_leases_lock = RLock()


@dataclass(frozen=True)
class ProbeProgress:
    devices: list[DiscoveredDevice]
    warnings: tuple[dict[str, str], ...]
    completed: int
    total: int


@dataclass
class _ProbePlan:
    row: DiscoveredDevice
    candidates: tuple[dict, ...]
    intent: dict
    aliases: set[str]
    eligible: bool


class ProbeCleanupError(RuntimeError):
    """Keep failed probe cleanup available for retry before releasing its lease."""

    def __init__(self, error, close, transport):
        super().__init__(f"{transport.upper()} probe cleanup failed: {error}")
        self.transport = transport
        self._close = close
        self._callbacks = []
        self._lock = RLock()

    def add_release_callback(self, callback):
        with self._lock:
            if self._close is not None:
                self._callbacks.append(callback)
                return
        callback()

    def retry_close(self):
        with self._lock:
            if self._close is None:
                return
            self._close()
            self._close = None
            callbacks, self._callbacks = self._callbacks, []
        for callback in callbacks:
            callback()


@contextmanager
def _probe_lease(devices, *, directory):
    """Hold the device lease until the probe handle closes successfully."""
    lease = HardwareLeaseSet.for_devices(devices, directory=directory)
    lease.acquire()
    deferred = False
    try:
        yield lease
    except (NativeHandleCleanupError, ProbeCleanupError) as owner:
        deferred = True
        key = id(owner)
        with _cleanup_leases_lock:
            _cleanup_leases[key] = (owner, lease)

        def released():
            lease.release()
            with _cleanup_leases_lock:
                _cleanup_leases.pop(key, None)

        owner.add_release_callback(released)
        raise
    finally:
        if not deferred:
            lease.release()


def _retry_probe_cleanup():
    with _cleanup_leases_lock:
        retained = list(_cleanup_leases.values())
    warnings = []
    for owner, _lease in retained:
        try:
            owner.retry_close()
        except Exception as exc:
            warnings.append({"transport": getattr(owner, "transport", "d2xx"), "code": "cleanup_pending",
                             "message": f"Probe handle cleanup remains unresolved: {exc}"})
    return warnings


def _access_denied(error: Exception) -> bool:
    if isinstance(error, PermissionError) or getattr(error, "winerror", None) in (5, 32, 33):
        return True
    # pyserial embeds Windows permission errors in the message, so checking
    # the exception type alone would miss a blocked COM port.
    from serial import SerialException

    return (isinstance(error, SerialException) and "could not open port" in str(error)
            and "PermissionError(" in str(error))


def probe_endpoint(endpoint: dict, connection: dict) -> PodProbe:
    """Read a POD's type without starting IPC queues, then close its handle.

    If closing fails, raise a cleanup error so the caller can retain the lease.
    """
    native = endpoint["transport"] == "d2xx"
    timeout = min(connection["read_timeout_ms"] / 1000, 2.0)
    pod = None
    opened = False
    read_observation = {"response": False, "error": False}
    try:
        pod_cls = _import_probe_class()
        pod = pod_cls(
            endpoint["address"],
            baudrate=connection["baudrate"],
            use_d2xx=native,
            d2xx_serial_only=native,
            flow_control=connection.get("flow_control") or ("rts_cts" if native else "none"),
            read_timeout_ms=min(connection["read_timeout_ms"], 2000),
            write_timeout_ms=min(connection["write_timeout_ms"], 2000),
            probe=True,
        )
        pod.open_port()
        opened = getattr(pod, "_port", None) is not None
        if not opened:
            return PodProbe(False, False, None, endpoint["hardware_id"], "busy")
        original_reader = getattr(pod, "read_pod_packet", None)
        if original_reader is not None:

            def observe_read(*args, **kwargs):
                try:
                    packet = original_reader(*args, **kwargs)
                except TimeoutError:
                    raise
                except Exception:
                    read_observation["error"] = True
                    raise
                read_observation["response"] = True
                return packet

            # The SDK retries bad or unrelated responses until it times out.
            # Record them so only silence permits a baud-rate retry.
            pod.read_pod_packet = observe_read
        type_number = _payload_value(pod, "TYPE", timeout)
        return PodProbe(
            True,
            True,
            type_number if isinstance(type_number, int) else None,
            endpoint["hardware_id"],
            None if type_number in TYPE_MAP else "probe_failed",
        )
    except NativeHandleCleanupError:
        # Let the caller retain the lease until cleanup succeeds.
        raise
    except Exception as exc:
        logger.warning(
            "Device identification failed: transport=%s address=%s opened=%s error=%s: %s",
            endpoint["transport"], endpoint["address"], opened, type(exc).__name__, exc,
        )
        if opened and isinstance(exc, TimeoutError) and not any(read_observation.values()):
            code = "probe_timeout"
        elif _access_denied(exc):
            code = "permission_denied"
        else:
            code = "probe_failed" if opened else "open_failed"
        return PodProbe(opened, False, None, endpoint["hardware_id"], code)
    finally:
        if pod is not None:
            try:
                _cleanup_pod(pod)
            except NativeHandleCleanupError:
                raise
            except Exception as exc:
                raise ProbeCleanupError(exc, lambda: _cleanup_pod(pod), endpoint["transport"]) from exc


def scan_endpoints(
    *,
    port_lister: Callable[[], Iterable[object]],
    native_lister: Callable[[], list[dict]] | None = None,
    prober: Callable[[dict, dict], PodProbe] = probe_endpoint,
    directory: str | Path,
    configured: Mapping[str, dict] | None = None,
    claimed: frozenset[str] = frozenset(),
    max_workers: int = 4,
    on_progress: Callable[[ProbeProgress], None] | None = None,
) -> tuple[list[DiscoveredDevice], tuple[dict[str, str], ...]]:
    """List VCP and D2XX endpoints and probe each physical device in one worker.

    Return inventory failures as warnings alongside devices from either provider.
    Skip claimed or busy devices and acquire an OS lease before probing.
    Auto mode tries VCP before D2XX, closing each probe before the next attempt.
    Hold the lease through transport changes and baud-rate retries.
    """
    warnings: list[dict[str, str]] = _retry_probe_cleanup()
    endpoints: list[dict] = []
    # list_d2xx_devices holds the driver gate through all descriptor reads
    # so another backend transaction cannot refresh the list partway through.
    try:
        native = (
            native_lister() if native_lister is not None
            else list_native_endpoints(reconcile=False)
        )
        endpoints.extend(dict(endpoint) for endpoint in native)
    except Exception as exc:
        warnings.append({
            "transport": "d2xx",
            "code": "backend_unavailable" if isinstance(exc, ImportError) else "enumeration_failed",
            "message": str(exc),
        })
    try:
        for info in port_lister():
            if _is_probe_candidate(info):
                address = _port_name(info)
                endpoints.append(
                    {
                        "hardware_id": _attribute(info, "serial_number", "serial", "hardware_id"),
                        "address": address,
                        "transport": "vcp",
                        "backend": "pyserial",
                        "label": _label(info, address),
                        "vid": _attribute(info, "vid"),
                        "pid": _attribute(info, "pid"),
                    }
                )
    except Exception as exc:
        warnings.append({"transport": "vcp", "code": "enumeration_failed", "message": str(exc)})

    # Keep VCP first in results even though D2XX was enumerated first.
    endpoints.sort(key=lambda endpoint: endpoint["transport"] != "vcp")
    grouped: dict[str, list[dict]] = {}
    unidentified: list[DiscoveredDevice] = []
    for endpoint in endpoints:
        identity = endpoint.get("hardware_id")
        if isinstance(identity, bytes):
            try:
                identity = identity.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                identity = None
        if not isinstance(identity, str) or not identity or identity != identity.strip():
            busy_without_identity = (
                endpoint["transport"] == "d2xx"
                and identity in (None, "")
                and bool(int(endpoint.get("flags") or 0) & 1)
            )
            code = "busy_identity_unavailable" if busy_without_identity else "identity_missing"
            message = (
                "An FTDI endpoint is already open and the driver did not report its serial. "
                "Close the connection using it, then rescan; probing skipped."
                if busy_without_identity else
                "An enumerated FTDI endpoint has no exact serial; probing skipped."
            )
            warnings.append(
                {
                    "transport": endpoint["transport"],
                    "code": code,
                    "message": message,
                }
            )
            endpoint.update(
                availability="unopenable", error_code=code, hardware_id=None
            )
            address = str(endpoint.get("address") or "Unknown FTDI address")
            unidentified.append(
                DiscoveredDevice(
                    type=DeviceType.UNKNOWN,
                    port=address,
                    hardware_id=None,
                    label=("Busy FTDI endpoint (identity unavailable)" if busy_without_identity
                           else str(endpoint.get("label") or "FTDI device without a serial")),
                    availability="unopenable",
                    endpoints=(endpoint,),
                    transport=None,
                    scan_key=f"unidentified:{len(unidentified)}",
                )
            )
            continue
        endpoint["hardware_id"] = identity
        if isinstance(endpoint.get("address"), bytes):
            endpoint["address"] = identity
        endpoint["availability"] = "unverified"
        grouped.setdefault(identity, []).append(endpoint)

    # Use one Windows device snapshot to match VCP and D2XX identities
    # so both interfaces share a probe plan.
    valid_endpoints = [endpoint for group in grouped.values() for endpoint in group]
    grouped = {}
    for endpoint in annotate_endpoints(valid_endpoints):
        grouped.setdefault(endpoint["hardware_id"], []).append(endpoint)

    def plan_device(item: tuple[str, list[dict]]) -> _ProbePlan:
        identity, physical_endpoints = item
        aliases = {identity}
        for endpoint in physical_endpoints:
            aliases.update(endpoint.get("aliases", ()))
        matching_configs = aliases.intersection(configured or {})
        if len(matching_configs) == 1:
            identity = next(iter(matching_configs))
        intent = normalize_connection((configured or {}).get(identity, {"preference": "auto"}))
        preference = intent["preference"]
        counts = Counter(endpoint["transport"] for endpoint in physical_endpoints)
        ambiguous = (
            len(matching_configs) > 1 or any(count > 1 for count in counts.values())
            or any(endpoint.get("identity_conflict") for endpoint in physical_endpoints)
        )
        choices = ("vcp", "d2xx") if preference == "auto" else (preference,)
        candidates = tuple(ep for transport in choices for ep in physical_endpoints
                           if ep["transport"] == transport)
        selected = candidates[0] if candidates else None
        driver_busy = any(int(ep.get("flags") or 0) & 1 for ep in physical_endpoints)
        eligible = not ambiguous and selected is not None and not aliases.intersection(claimed) and not driver_busy
        if ambiguous:
            for endpoint in physical_endpoints:
                endpoint.update(availability="unopenable", error_code="identity_ambiguous")
        elif driver_busy or aliases.intersection(claimed):
            for endpoint in physical_endpoints:
                endpoint.update(availability="unopenable", error_code="busy" if driver_busy else "claimed")
        display = selected or physical_endpoints[0]
        row = DiscoveredDevice(
            type=DeviceType.UNKNOWN,
            port=display["address"],
            hardware_id=identity,
            label=display.get("label") or identity,
            availability="unverified" if eligible else (
                "unopenable" if ambiguous or driver_busy or aliases.intersection(claimed) else "unavailable"
            ),
            endpoints=tuple(deepcopy(physical_endpoints)),
            transport=selected["transport"] if selected else None,
            scan_key=f"device:{display.get('physical_id') or item[0]}",
            probe_state="queued" if eligible else "complete",
        )
        return _ProbePlan(row, candidates, intent, aliases, eligible)

    # Resolve identities and settings before workers can open devices.
    plans = [plan_device(item) for item in grouped.items()]
    rows = [plan.row for plan in plans] + unidentified
    total = len(rows)
    completed = sum(row.probe_state == "complete" for row in rows)
    progress_lock = RLock()

    def publish():
        if on_progress is not None:
            on_progress(ProbeProgress(deepcopy([row for row in rows if row is not None]),
                                      deepcopy(tuple(warnings)), completed, total))

    def scan_device(index: int):
        plan = plans[index]
        endpoints = [dict(ep) for ep in plan.row.endpoints]
        selected = next(ep for ep in endpoints if ep["transport"] == plan.candidates[0]["transport"])
        identity = plan.row.hardware_id
        with progress_lock:
            rows[index] = replace(rows[index], probe_state="probing")
            publish()
        warning = None
        device_type, availability = DeviceType.UNKNOWN, "unavailable"
        try:
            lock_ids = {identity, selected.get("physical_id") or identity, *plan.aliases}
            with _probe_lease([(key, selected["address"]) for key in lock_ids], directory=directory):
                for candidate in plan.candidates:
                    selected = next(ep for ep in endpoints if ep["transport"] == candidate["transport"])
                    intent = dict(plan.intent)
                    result = prober(selected, intent)
                    if (selected["transport"] == "d2xx" and identity not in (configured or {})
                            and result.error_code == "probe_timeout"):
                        # Try the alternate baud rate only for an unconfigured
                        # D2XX device that produced no response or read error.
                        intent = {**intent, "baudrate": 115200}
                        result = prober(selected, intent)
                    if result.pinged and result.type_number in TYPE_MAP:
                        device_type, availability = TYPE_MAP[result.type_number], "available"
                        selected.update(availability=availability, error_code=None, baudrate=intent["baudrate"])
                        break
                    blocked = result.error_code in ("busy", "claimed", "permission_denied", "cleanup_pending")
                    availability = "unopenable" if blocked else "unavailable"
                    selected.update(availability=availability, error_code=result.error_code or "probe_failed")
                    if blocked:
                        # A blocked device must not be retried through its other interface.
                        break
        except HardwareLeaseBusy:
            availability = "unopenable"
            selected.update(availability=availability, error_code="busy")
        except (NativeHandleCleanupError, ProbeCleanupError) as exc:
            availability = "unopenable"
            warning = {"transport": selected["transport"], "code": "cleanup_pending", "message": str(exc)}
            selected.update(availability=availability, error_code="cleanup_pending")
        except Exception:
            availability = "unavailable"
            selected.update(availability=availability, error_code="probe_failed")
        return replace(plan.row, type=device_type, availability=availability,
                       port=selected["address"], transport=selected["transport"],
                       endpoints=tuple(endpoints), probe_state="complete"), warning

    # Show all discovered devices before probing delays individual results.
    publish()
    jobs = [i for i, plan in enumerate(plans) if plan.eligible]
    jobs.sort(key=lambda i: plans[i].row.transport != "vcp")
    if jobs:
        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 4, len(jobs))),
                                thread_name_prefix="device-probe") as executor:
            futures = {executor.submit(scan_device, i): i for i in jobs}
            for future in as_completed(futures):
                row, warning = future.result()
                with progress_lock:
                    rows[futures[future]] = row
                    completed += 1
                    if warning:
                        warnings.append(warning)
                    publish()
    return [row for row in rows if row is not None], tuple(warnings)
