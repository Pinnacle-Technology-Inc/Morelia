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

# local imports
from Morelia.Devices import AcquisitionDevice
from Morelia.Devices.SerialPorts import PortIO
from Morelia.Stream.source import get_data_wrapper
import Morelia.Stream.sink as pod_sink

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

    def stop_collection(self, join_timeout_sec: float = 15.0) -> None:
        """Stop collecting data.

        Sets the stop events so workers exit their loop. Waits up to
        ``join_timeout_sec`` for each worker to exit so they can send
        STREAM 0 to the device, flush sinks (e.g. PVFS), and close cleanly;
        if a worker is still alive (e.g. blocked in a serial read or disk I/O),
        it is terminated so the main process does not hang.
        """
        for event in self._manual_stop_events:
            event.set()

        self._manual_stop_events = []

        for worker in self._workers:
            worker.join(timeout=join_timeout_sec)
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=1.0)
            try:
                worker.close()
            except Exception:
                pass

        self._workers = []

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
   
