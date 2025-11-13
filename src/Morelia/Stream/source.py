"""Functions for getting streaming data from a POD device using `ReactiveX (RxPy) <https://rxpy.readthedocs.io/en/latest/index.html>`_."""

__author__      = 'James Hurd'
__maintainer__  = 'James Hurd'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2023, Thresa Kelly'
__email__       = 'sales@pinnaclet.com'

#environment imports
import traceback
from multiprocessing import Event
import threading
import time
from functools import partial
from contextlib import ExitStack

#local imports
from Morelia.Devices import Pod8206HR, Pod8401HR, Pod8274D, AcquisitionDevice

from Morelia.packet import ControlPacket

import reactivex as rx
from reactivex import operators as ops
from reactivex.operators import do_action

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
                now_real_time_ns = time.time_ns()
                predicted = int(observer.last_timestamp + (10**9 / observer.sample_rate))
                drift = now_real_time_ns - predicted

                correction_factor = 0.005

                #add on a fraction of the sample rate to last timestamp, plus drift correction
                observer.last_timestamp = int(predicted + (drift * correction_factor))

                # timestamps used to be this, without correction factors:
                # observer.last_timestamp = int(observer.last_timestamp + (10**9 / observer.sample_rate))

                # if predicted time is greater than current time, reset time stamps
                if observer.last_timestamp > now_real_time_ns: 
                    observer.last_timestamp = now_real_time_ns

                observer.packet_count += 1

                # if it's been more than a second...
                if time.perf_counter() - observer.time_at_last_update >= 1:
                    
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

                try:
                    observer.on_next(pod.read_pod_packet())
                except Exception as e:
                    print(f"Dropped packet due to {type(e).__name__}: {e}")
                    #traceback.print_exc()
                    continue
            pod.close_port()

        # tell the observer we are finished.
        observer.on_completed()
    return _stream_from_pod_device_observable

#function used by reactivex to place raw packets (binary) into the read queue
def make_packet_putter(read_queue):
    def put_read_packet(item):
        if isinstance(item, ControlPacket):
            try:
                read_queue.put_nowait(item._raw_packet)
            except Exception as e:
                print(f"[!] Failed to queue control packet: {e}")
    return put_read_packet

def get_data(duration: float, manual_stop_event: Event, pod: AcquisitionDevice, sinks) -> None: 
    """Streams data from the POD device. The data drops about every 1 second.
    Streaming will continue until a "stop streaming" packet is recieved. 

    :param duration: How long to stream data for.
    :param manual_stop_event: Used to synchronize multiple ``get_data`` operations in a flowgraph. When a flowgraph is told to stop collecting, \
            this event is set which stops the loop within the reactivex operator that is collecting data.
    :param pod: The device to collect data from.
    """
    
    #obtain read_queue from pod device
    read_queue = pod.obtain_read_queue()

    #obtain put read packet from the closure function
    put_read_packet = make_packet_putter(read_queue)

    # create an observable to stream from POD device.
    device = rx.create(_stream_from_pod_device(pod, duration, manual_stop_event))

    # create background queue 
    def background_writer(pod: AcquisitionDevice):
        while True:
            pod.check_write_queue()
            time.sleep(0.005) # sleep to avoid CPU performance issues

    threading.Thread(target=background_writer, args=(pod,), daemon=True).start()

    # pipe the packets from ``device`` into a filter that throws out control packets (eventually we don't want to do this, but have
    # a seperate place these get put so they can still be read during streaming to enable feedback.),
    # and them timestamp packets.
    
    data = device.pipe(
           do_action(lambda item: put_read_packet(item) if isinstance(item, ControlPacket) else None),
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

# wrapper function for get_data which reconstructs pod devices and sources after the process is created
def get_data_wrapper(duration_sec, manual_stop_event, source_class, source_dict, sinks_list):

    # obtain the source class
    source = source_class(**source_dict)

    # create list of sinks to use based on sink class/sink dictionary pair in the list
    sinks = [sink_class(**{**sink_dict, "pod": source}) for sink_class, sink_dict in sinks_list]

    # run get_data with the pod device and list of sinks 
    get_data(duration_sec, manual_stop_event, source, sinks)
