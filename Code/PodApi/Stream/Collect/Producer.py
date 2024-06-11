from multiprocessing import Event
from multiprocessing.connection import Connection
import time
from numpy import linspace
from functools import partial

from PodApi.Devices import Pod8206HR, Pod8401HR, Pod8274D
from PodApi.Packets import Packet, PacketStandard, PacketBinary
from PodApi.Stream.Collect import Valve

#TODO: type hint
def get_data(data_filter, duration: float, fail_tolerance, end_stream_event: Event, 
           manual_stop_event: Event, pipe: Connection, pod: Pod8206HR|Pod8401HR|Pod8274D): 
    """Streams data from the POD device. The data drops about every 1 second.
    Streaming will continue until a "stop streaming" packet is recieved. 

    Args: 
         fail_tolerance (int): The number of successive failed attempts of reading data before stopping the streaming.
    """
    
    # initialize       

    successive_fail_count: int = 0
    
    device_valve: Valve = Valve(pod)

    stop_bytes: bytes = device_valve.GetStopBytes()
    
    sample_rate = _get_sample_rate(pod)

    data_sender = partial(_send_data, pipe, data_filter, sample_rate)

    current_time_stamp : float = 0.0 

    stream_start_time : float = time.time()
    
    # start streaming data 
    device_valve.Open()
    
    #TODO: OR EVENT
    while time.time()-stream_start_time < duration and not manual_stop_event.is_set() : 
        # initialize
        data: list[Packet|None] = [None] * sample_rate

        inital_time = (round(time.time(),9)) # initial time (sec)

        # read data for one second
        num_data_points_tried: int = 0

        while num_data_points_tried < sample_rate: # operates like 'for i in range(sampleRate)'
            try:
                # check for too many failed packets 
                if successive_fail_count > fail_tolerance: 
                    # finish up
                    current_time_stamp = data_sender(current_time_stamp, inital_time, data)
                    return 

                # read data (vv exception raised here if bad checksum or packet read timeout vv)
                drip: Packet = device_valve.Drip()

                # check stop condition 
                current_time_stamp = time.time()

                if drip.rawPacket == stop_bytes:
                    
                    # finish up
                    current_time_stamp = data_sender(current_time_stamp, inital_time, data)
                    return 

                # save binary packet data and ignore standard packets
                if not isinstance(drip,PacketStandard): 
                    data[num_data_points_tried] = drip
                    num_data_points_tried += 1 # update looping condition 
                    successive_fail_count = 0 # reset after succsessful loop 

            except Exception as e: 
                # corrupted data here, leave None in data[i]
                num_data_points_tried += 1 # update looping condition        
                successive_fail_count += 1

        # drop data 
        current_time_stamp = data_sender(current_time_stamp, inital_time, data)


    # stop streaming
    device_valve.Close()
    end_stream_event.set()

#TODO: type hints
def _send_data(pipe: Connection, data_filter, sample_rate: int, current_time: float,
               inital_time: float, data: list[Packet|None]) -> float: 

    # get times 
    next_time = current_time + (round(time.time(),9) - inital_time)

    timestamps: list[float] = linspace( # evenly spaced numbers over interval.
        current_time,    # start time
        next_time,       # stop time
        sample_rate # number of items 
    ).tolist()

    # clean out corrupted data
    if data_filter(data,timestamps):

        pipe.send( (timestamps, data) )

    # finish
    return next_time

def _get_sample_rate(pod: Pod8206HR|Pod8401HR|Pod8274D ) -> int : 
    """Writes a command to the POD device to get its sample rate in Hz.

    Args:
        pod (Pod8206HR | Pod8401HR | Pod8274D): POD device to get the sample rate for.

    Raises:
        Exception: Cannot get the sample rate for this POD device.
        Exception: Could not connect to this POD device.

    Returns:
        int: Sample rate in Hz.
    """
    
    # Device  ::: cmd, command name,    args, ret, description
    # ----------------------------------------------------------------------------------------------
    # 8206-HR ::: 100, GET SAMPLE RATE, None, U16, Gets the current sample rate of the system, in Hz
    # 8401-HR ::: 100, GET SAMPLE RATE, None, U16, Gets the current sample rate of the system, in Hz
    # 8274D   ::: 256, GET SAMPLE RATE, None, U16, Gets the current sample rate of the system, in Hz
    # ----------------------------------------------------------------------------------------------
    # NOTE both 8206HR and 8401HR use the same command to start streaming. 
    # If there is a new device that uses a different command, add a method 
    # to check what type the device is (i.e isinstance(pod, PodClass)) 
    # and set the self.stream* instance variables accordingly.
    if( not isinstance(pod, Pod8274D)) : 
        pod._commands.ValidateCommand('GET SAMPLE RATE')
        if(not pod.TestConnection()) :
            raise Exception('[!] Could not connect to this POD device.')
        pkt: PacketStandard = pod.WriteRead('GET SAMPLE RATE')
        print("here", int(pkt.Payload()[0]))
        return int(pkt.Payload()[0]) 
    else :  
        if(not pod.TestConnection()) :  
            raise Exception ('[!] Could not connect to this POD device.')
        pkt: PacketBinary = pod.WriteRead('GET SAMPLE RATE')
        print("here2", int(pkt))
        return pkt
