"""Functions for getting streaming data from a POD device using `ReactiveX (RxPy) <https://rxpy.readthedocs.io/en/latest/index.html>`_."""

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
from Morelia.Devices import Pod8206HR, Pod8401HR, Pod8274D, AcquisitionDevice

from Morelia.packet import ControlPacket

import reactivex as rx
from reactivex import operators as ops

#TODO: __all__ to tell us what to export.

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

                # add on a fraction of the sample rate to last timestamp.
                observer.last_timestamp = int(observer.last_timestamp+(10**9/observer.sample_rate))
                observer.packet_count += 1
                
                # if it's been more than a second...
                if time.perf_counter() - observer.time_at_last_update > 1:
                    
                    # adjust sample rate to be closer to what we are actually getting
                    observer.sample_rate = observer.packet_count/(time.perf_counter()-observer.starting_time)
                    observer.time_at_last_update = time.perf_counter()
                
                # send packet and timestamp on its way.
                observer.on_next((observer.last_timestamp, value))

            return source.subscribe(on_next,
                observer.on_error,
                observer.on_completed,
                scheduler=scheduler)
        return rx.create(subscribe)
    return(_timestamp_via_adjusted_sample_rate_operator)

#TODO: type hints
#function used by reactivex to create an observable from a packet stream from an acquisition device.
def _stream_from_pod_device(pod: AcquisitionDevice, duration: float, manual_stop_event: Event):
    def _stream_from_pod_device_observable(observer, scheduler) -> None:
        
        with pod:
            stream_start_time : float = time.perf_counter()

            while time.perf_counter()-stream_start_time < duration and not manual_stop_event.is_set():
            
                observer.on_next(pod.read_pod_packet())

        # tell the observer we are finished.
        observer.on_completed()
    return _stream_from_pod_device_observable

def get_data(duration: float, manual_stop_event: Event, pod: AcquisitionDevice, sinks) -> None: 
    """Streams data from the POD device. The data drops about every 1 second.
    Streaming will continue until a "stop streaming" packet is recieved. 

    :param duration: How long to stream data for.
    :param manual_stop_event: Used to synchronize multiple ``get_data`` operations in a flowgraph. When a flowgraph is told to stop collecting, \
            this event is set which stops the loop within the reactivex operator that is collecting data.
    :param pod: The device to collect data from.
    """
    
    # create an observable to stream from POD device.
    device = rx.create(_stream_from_pod_device(pod, duration, manual_stop_event))
    
    # pipe the packets from ``device`` into a filter that throws out control packets (eventually we don't want to do this, but have
    # a seperate place these get put so they can still be read during streaming to enable feedback.),
    # and them timestamp packets.
    data = device.pipe(
           ops.filter(lambda i: not isinstance(i, ControlPacket)), #todo: more strict filtering
           _timestamp_via_adjusted_sample_rate(pod.sample_rate)
       )
    
    # create a function that outputs a connectable observable.
    streamer = ops.publish()
    
    # create a connectable observable from the pipeline we constructed earlier.
    stream = streamer(data)
    
    # now, subscribe each sink to the connectable observable. Since sinks implment the context manager protocol, we can use an ExitStack.
    #TODO: handle errors (via on_error, right now we just print them).
    with ExitStack() as context_manager_stack:

        send_to_sink = lambda sink, args: sink.flush(*args)
        
        for sink in sinks:
            context_manager_stack.enter_context(sink)
            
            stream.subscribe(on_next=partial(send_to_sink, sink), on_error=lambda e: print(e))
        
        # start streaming data from the observable!
        stream.connect()
