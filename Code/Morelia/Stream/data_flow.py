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
import asyncio

# local imports
from Morelia.Devices import Pod8206HR, Pod8401HR, Pod8274D
from Morelia.Stream.filter_data import FilterMethod, filter_data
from Morelia.Stream.source import get_data
import Morelia.Stream.sink as pod_sink

class DataFlow:
    """Class that use multiprocessing to efficiently collect data from many devices at once.

    :param network: A mapping of data sources (POD devices) to one or more data sinks.
    :type network: list[tuple[:class: Pod8206HR | :class: Pod8401HR | :class: Pod8274D, list[ :class: SinkInterface]]]

    :param filter_method: Method to use to clean curropted data. Defaults to TAKE_PAST.
    :type filter_method: FilterMethod, optional

    :param filter_insert_value: Value to insert when using the INSERT filter method. Defaults to NaN.
    :type filter_insert_value: float, optional
    
    :param fail_tolerance: How many times in a row to fail reading before giving up on reading a "chunk" of data ("chunk" here is approximately 1 second of samples). Defaults to 3.
    :type fail_tolerance: int, optional
    """

    def __init__(self, network: list[tuple[Pod8206HR|Pod8401HR|Pod8274D, list[pod_sink.SinkInterface]]], filter_method: FilterMethod = FilterMethod.TAKE_PAST, filter_insert_value: float = float('nan'), fail_tolerance: int = 3) -> None:
        """Set class instance variables."""

        self._filter_method: FilterMethod = filter_method
        self._data_filter = partial(filter_data, filter_method, filter_insert_value)
        self._fail_tolerance = fail_tolerance

        self._manual_stop_events: list[mp.Event] = [] #events in the case of infinite collection are stored here.
        self._network = network
        self._procs: list[tuple[mp.Process, mp.Process]] = []

    @property
    def filter_method(self) -> FilterMethod:
        return self._filter_method

    @property
    def fail_tolerance(self) -> int:
        return self.fail_tolerance

    def stop_collection(self) -> None:
        """Stop collecting data."""
        for event in self._manual_stop_events:
            event.set()

        self._manual_stop_events = []

        for producer, consumer in self._procs:
            producer.join()
            producer.close()
            consumer.join()
            consumer.close()

    def collect_for_seconds(self, duration_sec: float) -> None:
        """Collect data for `duration_sec` seconds.

        :param duration_sec: How long to collect data for in seconds.
        :type duration_sec: float
        """

        for producer, consumer in self._start_collecting(duration_sec):
            producer.join()
            producer.close()
            consumer.join()
            consumer.close()

        #clear out manual stop events.
        self._manual_stop_events = []

    def collect(self) -> None:
        """Collect until `stop_collection` is called."""
        self._procs = self._start_collecting()

    def _start_collecting(self, duration_sec: float = float('inf')) -> list[tuple[mp.Process, mp.Process]]:
        """Collect data from all sources and all sinks for `duration_sec` seconds.

        :raises ValueError: Raise an error for invalid combinations of sink and filter method.
        """
        
        procs = []

        #to begin, create all the process objects necessary for each source, sinks pair.
        for source, sinks in self._network:
 
            #specific filter methods are not compatible with the EDF format. If they are incompatible, raise an error.
            if self._filter_method in (FilterMethod.DO_NOTHING, FilterMethod.REMOVE) and any(map(partial(isinstance, EdfSink), sinks)):
                raise ValueError('Can only use EDF sink with INSERT, TAKE_PAST, and TAKE_FUTURE filters.')

            send: mp.connection.Connection
            recv: mp.connection.Connection
            send, recv = mp.Pipe()

            #this event is used to signal that the stream has ended.
            end_stream_event: mp.Event = mp.Event()

            #event that signals the stream has been stopped by `stop_collecting`.
            manual_stop_event: mp.Event = mp.Event()
            self._manual_stop_events.append(manual_stop_event)

            #create source and sink processes.
            source_proc: mp.Process = mp.Process(target=get_data, args=(self._data_filter, duration_sec, self._fail_tolerance, end_stream_event, manual_stop_event, send, source))

            sink_proc: mp.Process = mp.Process(target=self._start_sinks, args=(end_stream_event, recv, sinks))

            procs.append((source_proc, sink_proc))

        #start processes
        for source_proc, sink_proc in procs:
            source_proc.start()
            sink_proc.start()

        return procs

    def _start_sinks(self, end_stream_event: mp.Event, pipe: mp.connection.Connection, sinks: list[pod_sink.SinkInterface]):
        """Start event look to run sinks."""
        asyncio.run(self._start_sinks_async(end_stream_event, pipe, sinks))

    async def _start_sinks_async(self, end_stream_event: mp.Event, pipe: mp.connection.Connection, sinks: list[pod_sink.SinkInterface]):
        """Coroutine to run all sinks concurrently for a given source."""
        while not end_stream_event.is_set():
            async with asyncio.TaskGroup() as tg:
                #need to get data first to avoid suspected race condition.
                #if we pass *pipe.recv() directly into create_task, i believe
                #this causes the pipe to block trying to recieve data when there 
                #is none data but before the end_stream_event is set...
                data = pipe.recv()
                for sink in sinks:
                    tg.create_task(sink.flush(*data))
