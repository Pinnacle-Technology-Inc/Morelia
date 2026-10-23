"""Teardown policy for exited producers whose original receipt was unclean.

This evidence is control-plane observation, never watchdog telemetry. Missing
worker inventory or parent death alone cannot authorize claim release.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping

from app.runtime_host.process_evidence import ProcessEvidence, ProcessState


@dataclass(frozen=True)
class AdministrativeStopEvidence:
    runtime_id: str
    watchdog_id: str
    dataflow_id: str
    manifest_hash: str
    payload: dict
    observations: dict


def assess_containment_teardown(*, runtime_id: str, watchdog_id: str, dataflow_id: str,
                                manifest_hash: str, stop_intent: Mapping,
                                receipt: Mapping | None, host: ProcessEvidence,
                                generations: Mapping[str, Mapping],
                                expected_watchdogs: set[str],
                                hardware_leases_free: bool) -> AdministrativeStopEvidence | None:
    """Accept parent-observed process cleanup when workers cannot send shutdown reports."""
    if (host.state is not ProcessState.DEAD or not hardware_leases_free
            or not expected_watchdogs or set(generations) != expected_watchdogs
            or watchdog_id not in expected_watchdogs
            or any(item.get("released") is not True for item in generations.values())):
        return None
    if not all(stop_intent.get(key) for key in ("command_id", "requested_at", "stop_reason")):
        return None
    payload = dict(receipt or {})
    for key in ("command_id", "requested_at", "stop_reason"):
        payload.setdefault(key, stop_intent[key])
    payload.update(teardown_confirmed=True, output_integrity_confirmed=False,
                   errors=[*payload.get("errors", []), "Parent confirmed process-tree termination"])
    return AdministrativeStopEvidence(runtime_id, watchdog_id, dataflow_id, manifest_hash,
        payload, {"source": "parent_controlled_process_tree_cleanup",
                  "host": host.to_dict(), "generations": dict(generations),
                  "hardware_leases_free": True})


def ownership_teardown_confirmed(owner) -> bool:
    """A historical STOPPED label is not a producer-exit certificate."""
    details = owner.details or {}
    if (details.get("host_launch_failed") is True and owner.pid is None
            and not owner.watchdog_id and owner.watchdog_pid is None):
        return True
    if owner.watchdog_id and (owner.watchdog_exit_details or {}).get("teardown_confirmed") is True:
        return True
    record = details.get("administrative_stop_evidence") or {}
    return all(record.get(key) == getattr(owner, key) for key in (
        "runtime_id", "watchdog_id", "dataflow_id", "manifest_hash"
    )) and (record.get("payload") or {}).get("teardown_confirmed") is True


def workers_exited(result: Mapping, expected_streams: int) -> bool:
    """Require a receipt for every configured stream and retained generation."""
    current = result.get("stream_results")
    previous = result.get("previous_stream_results")
    if (result.get("worker_inventory_complete") is not True or expected_streams <= 0
            or not isinstance(current, list) or not isinstance(previous, list)):
        return False
    if len(current) != expected_streams or any(not isinstance(x, Mapping) for x in current + previous):
        return False
    indices = [x.get("stream_index") for x in current]
    if any(type(x) is not int for x in indices) or set(indices) != set(range(expected_streams)):
        return False
    for worker in current + previous:
        if (worker.get("worker_started") is False and worker.get("worker_status") == "not_started"
                and worker.get("teardown_confirmed") is True):
            continue
        if worker.get("descendants_teardown_confirmed") is not True:
            return False
        if worker.get("worker_exited") is not True or type(worker.get("worker_exitcode")) is not int:
            return False
    # Explicit driver resource failures are not repaired by process assertions.
    return result.get("resources_teardown_confirmed") is True


def assess_orphan_teardown(*, runtime_id: str, watchdog_id: str, dataflow_id: str,
                          manifest_hash: str, receipt: Mapping, expected_streams: int,
                          host: ProcessEvidence, watchdog: ProcessEvidence,
                          hardware_leases_free: bool,
                          predecessors_confirmed: bool = False) -> AdministrativeStopEvidence | None:
    if (host.state is not ProcessState.DEAD or watchdog.state is not ProcessState.DEAD
            or not hardware_leases_free or not predecessors_confirmed):
        return None
    result = receipt.get("shutdown_result")
    if not isinstance(result, Mapping) or not workers_exited(result, expected_streams):
        return None
    if not all(receipt.get(key) for key in ("command_id", "requested_at", "stop_reason")):
        return None
    return AdministrativeStopEvidence(runtime_id, watchdog_id, dataflow_id, manifest_hash,
        {**receipt, "teardown_confirmed": True, "output_integrity_confirmed": False,
         "errors": [*receipt.get("errors", []), "unclean producer exit independently reconciled"]},
        {"source": "control_plane_process_observation", "host": host.to_dict(),
         "watchdog": watchdog.to_dict(), "worker_inventory_complete": True,
         "hardware_leases_free": True, "predecessors_confirmed": True})
