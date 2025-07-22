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
from functools import partial

# local imports
from Morelia.Devices import AcquisitionDevice
from Morelia.Stream.source import get_data
import Morelia.Stream.sink as pod_sink

import time

class DataFlow:
    """Class that use multiprocessing to efficiently collect data from many devices at once.

    :param network: A mapping of data sources (POD devices) to one or more data sinks.

    :param filter_method: Method to use to clean curropted data. Defaults to TAKE_PAST.

    :param filter_insert_value: Value to insert when using the INSERT filter method. Defaults to NaN.
    
    :param fail_tolerance: How many times in a row to fail reading before giving up on reading a "chunk" of data ("chunk" here is approximately 1 second of samples). Defaults to 3.
    """

    def __init__(self, network: list[tuple[AcquisitionDevice, list[pod_sink.SinkInterface]]]) -> None:
        """Set class instance variables."""

        self._manual_stop_events: list[mp.Event] = [] #events that stop collection stored here.
        self._network = network
        self._workers: list[mp.Process] = []

    def stop_collection(self) -> None:
        """Stop collecting data."""
        for event in self._manual_stop_events:
            event.set()

        self._manual_stop_events = []

        for worker in self._workers:
            worker.join()
            worker.close()

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
            manual_stop_event: mp.Event = mp.Event()
            self._manual_stop_events.append(manual_stop_event)
            
            #create worker process.
            worker: mp.Process = mp.Process(target=get_data, args=(duration_sec, manual_stop_event, source, sinks))

            self._workers.append(worker)

        #start processes
        for worker in self._workers:
            worker.start()

    def __enter__(self) -> None:
        self.collect()

    def __exit__(self, *args, **kwargs) -> None:
        self.stop_collection()
        return False

