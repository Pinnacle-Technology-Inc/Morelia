"""Functions for getting streaming data from a POD device."""

__author__      = 'James Hurd'
__maintainer__  = 'James Hurd'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2023, Thresa Kelly'
__email__       = 'sales@pinnaclet.com'

#environment imports
from multiprocessing import Event
import time
from functools import partial
from contextlib import ExitStack

#local imports
from Morelia.Devices import Pod8206HR, Pod8401HR, Pod8274D, AquisitionDevice
from Morelia.Packets import Packet, PacketStandard, PacketBinary5, PacketBinary4

import reactivex as rx
from reactivex import operators as ops

counter = 0

#TODO: __all__ to tell us what to export.

#TODO: more extensively document why timing is hard.
#TODO: type hints
#reactivex operator to timestamp packets as we get them based on the average observed sample
#rate (# total packets/time elapsed). this way, our timestamps are more evenly distributed
#and more closely resemble the time at which they were read from the device (as opposed
#to things like transfer and buffering delays by the OS/USB messign with things.
def _timestamp_via_adjusted_sample_rate(starting_sample_rate: int):
    def _timestamp_via_adjusted_sample_rate_operator(source):
        def subscribe(observer, scheduler=None):

            observer.sample_rate = starting_sample_rate
            observer.time_at_last_update = time.perf_counter()
            observer.starting_time = time.perf_counter()
            observer.last_timestamp = time.time_ns()
            observer.packet_count = 0

            def on_next(value):
                observer.last_timestamp = int(observer.last_timestamp+(10**9/observer.sample_rate))
                observer.packet_count += 1

                if time.perf_counter() - observer.time_at_last_update > 1:

                    observer.sample_rate = observer.packet_count/(time.perf_counter()-observer.starting_time)
                    observer.time_at_last_update = time.perf_counter()

                observer.on_next((observer.last_timestamp, value))

            return source.subscribe(on_next,
                observer.on_error,
                observer.on_completed,
                scheduler=scheduler)
        return rx.create(subscribe)
    return(_timestamp_via_adjusted_sample_rate_operator)

#TODO: type hints
#TODO: remove counter
#function used by reactivex to create an observable from a packet stream from an aquisition device.

def _stream_from_pod_device(pod: AquisitionDevice, duration: float, manual_stop_event: Event):
    def _stream_from_pod_device_observable(observer, scheduler) -> None:
        
        global counter

        with pod:
            stream_start_time : float = time.perf_counter()

            while time.perf_counter()-stream_start_time < duration and not manual_stop_event.is_set():
            
                observer.on_next(pod.ReadPODpacket())
                counter += 1

        observer.on_completed()
    return _stream_from_pod_device_observable

def get_data(duration: float, manual_stop_event: Event, pod: AquisitionDevice, sinks) -> None: 
    """Streams data from the POD device. The data drops about every 1 second.
    Streaming will continue until a "stop streaming" packet is recieved. 

    Args: 
         fail_tolerance (int): The number of successive failed attempts of reading data before stopping the streaming.
    """

    device = rx.create(_stream_from_pod_device(pod, duration, manual_stop_event))

    data = device.pipe(
           ops.filter(lambda i: not isinstance(i, PacketStandard)), #todo: more strict filtering
           _timestamp_via_adjusted_sample_rate(pod.sample_rate)
       )
    
    streamer = ops.publish()

    stream = streamer(data)

    #TODO: handle errors
    with ExitStack() as context_manager_stack:

        send_to_sink = lambda sink, args: sink.flush(*args)
        
        for sink in sinks:
            context_manager_stack.enter_context(sink)
            
            stream.subscribe(on_next=partial(send_to_sink, sink), on_error=lambda e: print(e))

        stream.connect()

    global counter

    print(pod.device_name, counter)
