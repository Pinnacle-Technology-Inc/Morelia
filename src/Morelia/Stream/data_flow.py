"""Stream data from multiple devices to multiple destinations. In technical terms, this module is used to create
bipartite dataflow graphs from devices to data sinks.
"""

__author__      = 'James Hurd'
__maintainer__  = 'James Hurd'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2023, James Hurd'
__email__       = 'sales@pinnaclet.com'

# environment imports
import multiprocessing as mp
from multiprocessing import Event
from functools import partial
import sys
import time
import gc
import uuid
from queue import Empty

# local imports
from Morelia.Devices import AcquisitionDevice
from Morelia.Devices.SerialPorts import PortIO
from Morelia.Stream.source import get_data_wrapper
import Morelia.Stream.sink as pod_sink
from Morelia.Stream.shutdown import (
    ShutdownAction,
    ShutdownActor,
    ShutdownOutcome,
    ShutdownPhase,
    ShutdownProtocol,
)


def coordinate_shutdown(worker, stop_event, status_queue, shutdown_id, stream_index, join_timeout_sec):
    """Coordinate one worker stop with one absolute deadline and one reducer."""
    protocol = ShutdownProtocol(shutdown_id, stream_index)
    protocol.request()
    if stop_event is not None:
        stop_event.set()

    deadline = time.monotonic() + max(0.0, float(join_timeout_sec))
    while worker is not None and worker.is_alive():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if status_queue is not None:
            try:
                protocol.apply(status_queue.get(timeout=min(remaining, 0.05)))
                continue
            except Empty:
                pass
        worker.join(timeout=0)

    if worker is not None and worker.is_alive():
        protocol.deadline_expired()
        protocol.force_termination_requested()
        worker.terminate()
        worker.join(timeout=1.0)
        protocol.forced_termination(worker_exitcode=getattr(worker, "exitcode", None))
    elif worker is not None:
        worker.join(timeout=0)

    # A multiprocessing queue can receive the worker's final records after the
    # child has stopped. Drain only what is already queued; never use empty().
    if status_queue is not None:
        while True:
            try:
                protocol.apply(status_queue.get_nowait())
            except Empty:
                break

    if protocol.snapshot().phase not in (
        ShutdownPhase.FAILED,
        ShutdownPhase.COMPLETE,
        ShutdownPhase.PHASE_FAILED,
        ShutdownPhase.PROTOCOL_VIOLATION,
        ShutdownPhase.DEADLINE_EXPIRED,
    ):
        exit_action = ShutdownAction(
            shutdown_id=shutdown_id,
            stream_index=stream_index,
            actor=ShutdownActor.MONITOR,
            actor_pid=None,
            phase=ShutdownPhase.WORKER_EXITED,
            action="worker_exit_observed",
            outcome=ShutdownOutcome.COMPLETED,
            emitted_at_ns=0,
            worker_exitcode=getattr(worker, "exitcode", None),
        )
        protocol.apply(exit_action)

    snapshot = protocol.snapshot()
    if snapshot.phase not in (
        ShutdownPhase.COMPLETE,
        ShutdownPhase.FAILED,
        ShutdownPhase.PHASE_FAILED,
        ShutdownPhase.PROTOCOL_VIOLATION,
        ShutdownPhase.DEADLINE_EXPIRED,
    ):
        protocol.complete()
        snapshot = protocol.snapshot()
    if snapshot.phase not in (ShutdownPhase.COMPLETE, ShutdownPhase.FAILED):
        protocol.fail("missing_required_acknowledgement")
        snapshot = protocol.snapshot()

    return {
        "ok": snapshot.ok is True,
        "stream_index": stream_index,
        "worker_status": "stopped" if snapshot.ok is True else "failed",
        "shutdown_id": shutdown_id,
        "terminal_phase": snapshot.phase.value,
        "shutdown_phase": snapshot.phase.value,
        "forced_termination": snapshot.forced_termination,
        "worker_exitcode": snapshot.worker_exitcode
        if snapshot.worker_exitcode is not None
        else getattr(worker, "exitcode", None),
        "missing_phases": [phase.value for phase in snapshot.missing_phases],
        "transcript": snapshot.transcript,
        "shutdown_transcript": snapshot.transcript,
    }

class DataFlow:
    """Class that use multiprocessing to efficiently collect data from many devices at once.

    :param network: A mapping of data sources (POD devices) to one or more data sinks.

    :param filter_method: Method to use to clean curropted data. Defaults to TAKE_PAST.

    :param filter_insert_value: Value to insert when using the INSERT filter method. Defaults to NaN.
    
    :param fail_tolerance: How many times in a row to fail reading before giving up on reading a "chunk" of data ("chunk" here is approximately 1 second of samples). Defaults to 3.

    :param on_sink_error: Optional callback for handling sink failures. It receives one structured `SinkError` per failing sink, defaults to logging, and is picklable when used with multiprocessing.
    :param on_source_error: Optional callback for bounded source-read status events.
    """

    def __init__(
        self,
        network: list[tuple[AcquisitionDevice, list[pod_sink.SinkInterface]]],
        on_sink_error=None,
        on_source_error=None,
    ) -> None:
        """Set class instance variables."""

        self._manual_stop_events: list[mp.Event] = [] #events that stop collection stored here.
        self._shutdown_status_queues: list[object | None] = []
        self._shutdown_ids: list[str | None] = []
        self._network = network
        self._workers: list[mp.Process] = []
        self._on_sink_error = on_sink_error
        self._on_source_error = on_source_error

    def stop_collection(self, join_timeout_sec: float = 15.0):
        """Stop collecting data.

        Sets the stop events so workers exit their loop. Waits up to
        ``join_timeout_sec`` for each worker to exit so they can send
        STREAM 0 to the device, flush sinks (e.g. PVFS), and close cleanly;
        if a worker is still alive (e.g. blocked in a serial read or disk I/O),
        it is terminated so the main process does not hang.
        """
        results = []
        for index, worker in enumerate(self._workers):
            stop_event = self._manual_stop_events[index] if index < len(self._manual_stop_events) else None
            status_queue = self._shutdown_status_queues[index] if index < len(self._shutdown_status_queues) else None
            shutdown_id = self._shutdown_ids[index] if index < len(self._shutdown_ids) else str(uuid.uuid4())
            result = coordinate_shutdown(
                worker,
                stop_event,
                status_queue,
                shutdown_id,
                index,
                join_timeout_sec,
            )
            results.append(result)
            if status_queue is not None:
                close = getattr(status_queue, "close", None)
                if callable(close):
                    close()
                join_thread = getattr(status_queue, "join_thread", None)
                if callable(join_thread):
                    join_thread()
            try:
                worker.close()
            except Exception:
                pass

        self._manual_stop_events = []
        self._shutdown_status_queues = []
        self._shutdown_ids = []
        self._workers = []
        return {"ok": all(result["ok"] for result in results), "stream_results": results}

    def collect_for_seconds(self, duration_sec: float) -> None:
        """Collect data for ``duration_sec`` seconds.

        :param duration_sec: How long to collect data for in seconds.
        """
        self._start_collecting(duration_sec)

        for worker in self._workers:
            worker.join()
            worker.close()

        #clear out manual stop events.
        self._manual_stop_events = []
        self._shutdown_status_queues = []
        self._shutdown_ids = []

    def collect(self) -> None:
        """Collect until ``stop_collection`` is called."""
        self._start_collecting()

    def _start_collecting(self, duration_sec: float = float('inf')) -> None:
        """Collect data from all sources and all sinks for `duration_sec` seconds.

        :raises ValueError: Raise an error for invalid combinations of sink and filter method.
        """
        #to begin, create all the process objects necessary for each source, sinks pair.
        for source, sinks in self._network:

            #event that signals the stream has been stopped by `stop_collecting`.
            manual_stop_event = Event()
            
            self._manual_stop_events.append(manual_stop_event)
            self._shutdown_status_queues.append(mp.Queue())
            self._shutdown_ids.append(str(uuid.uuid4()))

            # close the port and delete the port instance
            # may want to use property here instead for better practice
            if hasattr(source, "_port"):
                source.close_port()

            gc.collect()

            # gets the type (class) of the pod device
            source_class = type(source)

            # uses the pod devices' get_dict function to return parameter values in a dictionary 
            source_dict = source.get_dict()
            
            # gets the class and dictionary of parameters of each sink in the sink list
            sinks_list = [
                (type(sink), sink.get_dict()) for sink in sinks
            ]

            # Create worker process. On Unix (when supported), use a new session so only the main
            # process receives SIGINT (Ctrl+C); the worker then stops only when manual_stop_event
            # is set and can run sink __exit__ (flush/close PVFS, etc.).
            worker_args = (#gather worker args here as per DRY
                duration_sec,
                manual_stop_event,
                source_class,
                source_dict,
                sinks_list,
                self._on_sink_error,
                self._on_source_error,
                self._shutdown_status_queues[-1],
                self._shutdown_ids[-1],
                len(self._manual_stop_events) - 1,
            )
            worker: mp.Process
            if sys.platform != "win32":
                try:
                    worker = mp.Process(
                        target=get_data_wrapper,
                        args=worker_args,
                        start_new_session=True,
                    )
                except TypeError:
                    worker = mp.Process(
                        target=get_data_wrapper,
                        args=worker_args,
                    )
            else:
                worker = mp.Process(
                    target=get_data_wrapper,
                    args=worker_args,
                )

            self._workers.append(worker)

        #start processes
        for worker in self._workers:
            worker.start()

    def __enter__(self) -> None:
        self.collect()

    def __exit__(self, *args, **kwargs) -> None:
        self.stop_collection()
        return False
   
