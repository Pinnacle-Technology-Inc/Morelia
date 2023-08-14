# enviornment imports
from threading import Thread
import numpy as np
import time

# local imports
from PodApi.Devices import Pod
from PodApi.Packets import Packet, PacketStandard
from PodApi.DataStream import Valve

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Hose : 
    
    def __init__(self, 
                 podDevice: Pod, 
                 streamCmd: str|int, 
                 streamPldStart: int|bytes|tuple[int|bytes], 
                 streamPldStop: int|bytes|tuple[int|bytes],
                 sampleRate: int) -> None:
        # check for valid parameters
        if(sampleRate < 1) : 
            raise Exception('[!] The sample rate mus be greater than zero.')
        # set variables 
        self.sampleRate  : int   = int(sampleRate)
        self.deviceValve : Valve = Valve(podDevice, streamCmd, streamPldStart, streamPldStop)
        self.data: list[Packet|None] = []
        self.timestamps: list[float] = []
        self.numDrops: int = 0
        
    def StartStream(self) : 
        # check for good connection 
        if(not self.deviceValve.podDevice.TestConnection()): 
            raise Exception('Could not connect to this POD device.')
        stream = Thread( target = self._Flow )
        # start streaming (program will continue until .join() or streaming ends)
        stream.start() 
        return(stream)
            
    def StopStream(self) : 
        # stop streaming
        self.deviceValve.Close()
        
    def _Flow(self) :  
        # initialize       
        stopAt: bytes = self.deviceValve.podDevice.GetPODpacket(
            cmd=self.deviceValve.streamCmd,
            payload=self.deviceValve.streamPldStop
        )
        currentTime : float = 0.0 
        # start streaming data 
        self.deviceValve.Open()
        while(True) : 
            # initialize
            data = [None] * self.sampleRate
            ti = (round(time.time(),9)) # initial time (sec)
            # read data for one second
            i: int = 0
            while (i < self.sampleRate) : # operates like 'for i in range(sampleRate)'
                try : 
                    # read data (vv exception raised here if bad checksum vv)
                    r: Packet = self.deviceValve.podDevice.ReadPODpacket()
                    # check stop condition 
                    if(r.rawPacket == stopAt) : 
                        # finish up
                        currentTime = self._Drop(currentTime, ti, data)
                        return # NOTE this is only exit for while(True) 
                    # save binary packet data and ignore standard packets
                    if( not isinstance(r,PacketStandard)) : 
                        data[i] = r
                        i += 1 # update looping condition 
                except : 
                    # corrupted data here, leave None in data[i]
                    i += 1 # update looping condition                 
            currentTime = self._Drop(currentTime, ti, data)

    def _Drop(self, currentTime: float, ti: float, data) : 
        # get times 
        nextTime = currentTime + (round(time.time(),9) - ti)
        # update trackers before looping again
        self.timestamps = np.linspace( # evenly spaced numbers over interval.
            currentTime,    # start time
            nextTime,       # stop time
            self.sampleRate # number of items 
        ).tolist()
        self.data = data
        self.numDrops += 1
        # finish
        return nextTime