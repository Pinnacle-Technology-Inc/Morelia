"""Dashboard-owned worker evidence layered on ordinary Watchdog orchestration."""

import time
import uuid
from multiprocessing.process import BaseProcess

from Morelia.Watchdog.dataflowMonitor import DataFlowMonitor

from app.runtime_child.acknowledged_dataflow import (
    _close_queue,
    _coordinate_worker_shutdown,
    _create_shutdown_queue,
    _sinks_may_own_processes,
)


class AcknowledgedDataFlowMonitor(DataFlowMonitor):
    """Keep dashboard shutdown policy out of the reusable Morelia watchdog."""

    def _stop_stream_unlocked(self, stream_index, join_timeout_sec, *, deadline=None):
        if deadline is None:
            deadline = time.monotonic() + max(0.0, float(join_timeout_sec))
        self.flowgraph.publish_shutdown_deadline(deadline, stream_index)
        return super()._stop_stream_unlocked(stream_index, join_timeout_sec, deadline=deadline)

    def _stop_stream_reserved(self, stream_index, join_timeout_sec):
        result = super()._stop_stream_reserved(stream_index, join_timeout_sec)
        with self._stream_lock(stream_index):
            self._retire_exited_worker(stream_index, result)
        return result

    def _retire_exited_worker(self, stream_index, result):
        """Allow device recovery after worker exit, preserving an unclean shutdown receipt."""
        workers = self.flowgraph._workers
        worker = workers[stream_index] if stream_index < len(workers) else None
        if worker is not None:
            if worker.is_alive() or worker.exitcode is None:
                return False
            self._close_worker_status_queue(stream_index)
            worker.close()
            workers[stream_index] = None
        return result.get("worker_exited") is True or result.get("teardown_confirmed") is True

    def _restart_one_stream_reserved(self, stream_index, join_timeout_sec):
        """Restart an exited acquisition worker even when graceful cleanup was incomplete."""
        with self._stream_lock(stream_index):
            self.dataflow_status = "restarting"
            try:
                stopped = self._stop_stream_unlocked(stream_index, join_timeout_sec)
                if not self._retire_exited_worker(stream_index, stopped):
                    raise RuntimeError("Acquisition worker exit is unconfirmed; recovery needs attention")
                reset = self.reset_stream_device(stream_index)
                if not reset.get("ok"):
                    raise RuntimeError(f"Device reset failed: {reset.get('error', 'unknown error')}")
                heartbeat = self._clear_stream_heartbeat_unlocked(stream_index)
                result = self._start_stream_unlocked(stream_index)
                result["reset_result"] = reset
                result["heartbeat_reset"] = heartbeat
                self.last_error = None
            except Exception as exc:
                self.dataflow_status = "restart_failed"
                self.last_error = f"{type(exc).__name__}: {exc}"
                return {"ok": False, "stream_index": stream_index, "error": self.last_error,
                        "dataflow_status": self.dataflow_status}
        result["dataflow_status"] = self.update_dataflow_status_from_workers()
        return result

    def _stop_worker(self, worker, stop_event, stream_index, join_timeout_sec, *, deadline=None):
        launch_not_attempted = self.flowgraph._worker_start_attempted.get(stream_index) is False
        if worker is None and not launch_not_attempted:
            # Outage handling may already have stopped this generation and
            # cleared its worker slot. Preserve its actual receipt, including
            # failure/forced evidence; a missing slot is not new stop evidence.
            retained = self.flowgraph._shutdown_results.get(stream_index)
            if retained is not None:
                if retained.get("teardown_confirmed") is True:
                    self._close_worker_status_queue(stream_index)
                return dict(retained)
            result = super()._stop_worker(
                worker,
                stop_event,
                stream_index,
                join_timeout_sec,
                deadline=deadline,
            )
            return {
                **result,
                "terminal_phase": "complete" if result["ok"] else "failed",
                "missing_phases": [] if result["ok"] else ["worker_exited"],
                "transcript": (),
                "shutdown_transcript": (),
            }

        queues = self.flowgraph._shutdown_status_queues
        ids = self.flowgraph._shutdown_ids
        status_queue = queues[stream_index] if stream_index < len(queues) else None
        shutdown_id = ids[stream_index] if stream_index < len(ids) else str(uuid.uuid4())
        result = _coordinate_worker_shutdown(
            worker,
            stop_event,
            status_queue,
            shutdown_id,
            stream_index,
            join_timeout_sec,
            deadline=deadline,
            previous=self.flowgraph._shutdown_results.get(stream_index),
            descendants_possible=self.flowgraph.descendants_possible(stream_index),
            launch_not_attempted=launch_not_attempted,
            descendants_released=self.flowgraph._descendants_released.get(stream_index),
        )
        self.flowgraph._shutdown_results[stream_index] = dict(result)
        if result.get("teardown_confirmed") is True:
            self._close_worker_status_queue(stream_index)
        return result

    def _close_worker_status_queue(self, stream_index):
        queues = self.flowgraph._shutdown_status_queues
        if stream_index < len(queues):
            _close_queue(queues[stream_index])
            queues[stream_index] = None

    def _start_worker(self, duration_sec, manual_stop_event, source, sinks, stream_index):
        status_queue = _create_shutdown_queue()
        shutdown_id = str(uuid.uuid4())
        worker = None
        try:
            worker = self._make_worker(
                duration_sec=duration_sec,
                manual_stop_event=manual_stop_event,
                source=source,
                sinks=sinks,
                stream_index=stream_index,
                status_queue=status_queue,
                shutdown_id=shutdown_id,
            )
            guard = getattr(self.flowgraph, "_acquisition_guard", None)
            if guard is not None:
                guard()
            worker.start()
            self.flowgraph._ever_started_worker = True
        except BaseException:
            if isinstance(worker, BaseProcess) and (worker._popen is not None
                                                    or worker.pid is not None):
                # start() can fail after acquiring a real child process. The
                # caller will not publish its return value, so retain it here.
                self._commit_worker_generation(stream_index, worker, manual_stop_event,
                                               status_queue, shutdown_id, sinks)
                self.flowgraph._ever_started_worker = True
                raise
            _close_queue(status_queue)
            raise

        self._commit_worker_generation(stream_index, worker, manual_stop_event,
                                       status_queue, shutdown_id, sinks)
        return worker

    def _commit_worker_generation(self, stream_index, worker, stop_event,
                                  status_queue, shutdown_id, sinks):
        """Publish an acquired child even if its launch did not return cleanly."""
        queues = self.flowgraph._shutdown_status_queues
        ids = self.flowgraph._shutdown_ids
        while len(queues) <= stream_index:
            queues.append(None)
        while len(ids) <= stream_index:
            ids.append(None)
        queues[stream_index] = status_queue
        ids[stream_index] = shutdown_id
        self.flowgraph._shutdown_generation_ids.add(shutdown_id)
        self.flowgraph._shutdown_descendants_possible[stream_index] = _sinks_may_own_processes(sinks)
        self.flowgraph._worker_start_attempted[stream_index] = True
        while len(self.flowgraph._workers) <= stream_index:
            self.flowgraph._workers.append(None)
        while len(self.flowgraph._manual_stop_events) <= stream_index:
            self.flowgraph._manual_stop_events.append(None)
        self.flowgraph._workers[stream_index] = worker
        self.flowgraph._manual_stop_events[stream_index] = stop_event
        # A newly acquired child starts a new generation. A failed construction
        # with no child leaves the earlier receipt in its original slot.
        previous = self.flowgraph._shutdown_results.pop(stream_index, None)
        if previous is not None:
            self.flowgraph.retain_previous_shutdown(previous)

    def _stop_dataflow_reserved(self, join_timeout_sec):
        self.flowgraph.publish_shutdown_deadline(
            time.monotonic() + max(0.0, float(join_timeout_sec)))
        result = super()._stop_dataflow_reserved(join_timeout_sec)
        previous = self.flowgraph._prior_shutdown_results
        result["previous_stream_results"] = [dict(item) for item in previous]
        all_results = [*result.get("stream_results", []), *previous]
        inventory_complete = self.flowgraph.worker_inventory_complete(result.get("stream_results", []))
        result["worker_inventory_complete"] = inventory_complete
        result["teardown_confirmed"] = (
            inventory_complete and "stream_results" in result
            and not any(queue is not None for queue in self.flowgraph._shutdown_status_queues)
            and all(item.get("teardown_confirmed") is True for item in all_results)
        )
        if not inventory_complete:
            result["ok"] = False
        if any(item.get("ok") is not True or item.get("forced_termination") for item in previous):
            result["ok"] = False
            result["forced_termination"] = bool(result.get("forced_termination")) or any(
                item.get("forced_termination") is True for item in previous)
            result["error"] = result.get("error") or "prior_stream_shutdown_unclean"
            result["dataflow_status"] = self.dataflow_status = "stop_failed"
            self.last_error = result["error"]
        return result

    def _make_worker(
        self,
        duration_sec,
        manual_stop_event,
        source,
        sinks,
        *,
        stream_index=0,
        status_queue=None,
        shutdown_id=None,
    ):
        return self.flowgraph.make_worker(
            duration_sec,
            manual_stop_event,
            source,
            sinks,
            status_queue=status_queue,
            shutdown_id=shutdown_id,
            stream_index=stream_index,
        )

    def _clear_worker_state(self):
        if any(queue is not None for queue in self.flowgraph._shutdown_status_queues):
            return
        super()._clear_worker_state()
        if not self.flowgraph._workers:
            self.flowgraph._shutdown_status_queues = []
            self.flowgraph._shutdown_ids = []
