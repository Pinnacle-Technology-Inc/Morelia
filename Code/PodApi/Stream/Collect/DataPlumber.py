# environment imports
import multiprocessing as mp
import os
import time
import concurrent.futures as ft
from functools import partial

# local imports
from PodApi.Devices import Pod8206HR, Pod8401HR, Pod8274D
from PodApi.Stream.Collect.Producer import drain
from PodApi.Stream.Collect.Filter import FilterMethod, filter_data
from PodApi.Stream.Collect.Producer import get_data

# authorship
__author__      = "James Hurd"
__maintainer__  = "James Hurd"
__credits__     = ["James Hurd", "Sam Groth", "Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, James Hurd"
__email__       = "sales@pinnaclet.com"

#need to start/stop stream and empty stuff
class Plumber:
    """Class that use multiprocessing to efficiently collect data from many devices at once.

     Attributes:
        producers (dict[ str, Queue[ tuple[ list[float], producers ] ] ]): Dictionary that maps port names to producers.
        isCollecting (bool): True when collecting drops from the producer, False otherwise.
    """

    def __init__(self, podDevices: list[Pod8206HR|Pod8401HR|Pod8274D], filter_method: FilterMethod = FilterMethod.TAKE_PAST, filter_insert_value: float = float('nan')) -> None:
        """Set class instance variables.

        Args:
            podDevices (list[Pod8206HR | Pod8401HR | 8274D)]: POD devices to stream data from. Will use a process per device.
            filterMethod (str): Which filter to use. Options are: TakePast (default), TakeFuture, InsertValue, RemoveEntry, DoNothing.
            filterInsert (float): If using insert filer, the value to insert.
        """
        
        self._data_filter = partial(filter_data, filter_method, filter_insert_value)
        self._fail_tolerance = 3

        self._manual_stop_events: list[mp.Event] = [] #events in the case of infinite collection are stored here.
        self._workers: list[tuple[mp.Process, mp.Process]] = []

        #self._ports: list[str] = [ pod.GetPortName() for pod in podDevices ]
        self._pods: list[Pod8206HR|Pod8401HR|Pod8274D] = podDevices

        #self._pipes: list[tuple[mp.Connection, mp.Connection]] = [ mp.Pipe() for _ in podDevices ]
        #self._events: list[mp.Event] = [ mp.Event() for _ in self._pipes ]

        #self._producers: dict[str, producer] = { pod.GetPortName(): Hose(pod, send, event, filterMethod=filterMethod, filterInsert=filterInsert) for pod, event, ( send, _ ) in zip(podDevices, self._events, self._pipes) }
        #self._consumers: dict[str, Drain] = { port: Drain(recv, event) for port, event, ( _, recv ) in zip(self._ports, self._events, self._pipes) }
        #self.isCollecting: bool = False
    
    def StopInfiniteCollect(self) -> None: 
        for event in self._manual_stop_events:
            event.set()

        self.manual_stop_events = []

        for producer, consumer in self._workers:
            producer.join()
            producer.close()
            consumer.join()
            consumer.close()


    def FiniteCollect(self, duration_sec: float) -> None:
        for producer, consumer in self._StartCollecting(duration_sec):
            producer.join()
            producer.close()
            consumer.join()
            consumer.close()
        
    def InfiniteCollect(self) -> None:
        self._workers = self._StartCollecting()
    
    #i dont use an executor cuz it does some weird things with sharing Event objects. It feels weird to submit to a pool of workers when
    #i want a specific number of workers w/ no queue
    def _StartCollecting(self, duration_sec: float = float('inf')) -> list[tuple[mp.Process, mp.Process]]: 
            
            processes: list[tuple[mp.Process, mp.Process]] = []
            
            for pod in self._pods:

                send: mp.Connection
                recv: mp.Connection
                send, recv = mp.Pipe()

                end_stream_event: mp.Event = mp.Event()
                manual_stop_event: mp.Event = mp.Event()
                self._manual_stop_events.append(manual_stop_event)

                producer: mp.Process = mp.Process(target=get_data, args=(self._data_filter, duration_sec, self._fail_tolerance, end_stream_event, manual_stop_event, send, pod))
                consumer: mp.Process = mp.Process(target=drain, args=(recv, end_stream_event))

                producer.start()
                consumer.start()

                processes.append((producer, consumer))

            return processes
