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
        
        self.data: list[Packet|None]|None = None
        self.timestamps: list[float]|None = None
        self.numFlowLoops: int = 0
        
    def StartStream(self) : 
        # check for good connection 
        if(not self.TestDeviceConnection(self.deviceValve.podDevice)): 
            raise Exception('Could not connect to this POD device.')
        stream = Thread( target = self.Flow )
        # start streaming (program will continue until .join() or streaming ends)
        stream.start() 
        return(stream)
            
    def StopStream(self) : 
        # stop streaming
        self.deviceValve.Close()
        
    def Flow(self) :         
        stopAt: bytes = self.deviceValve.podDevice.GetPODpacket(
            cmd=self.deviceValve.streamCmd,
            payload=self.deviceValve.streamPldStop
        )
        currentTime : float = 0.0 

        self.deviceValve.Open()
        while(True) : 
            # initialize
            data = [None] * self.sampleRate
            ti = (round(time.time(),9)) # initial time (sec)
            # read data for one second
            i: int = 0
            while (i < self.sampleRate) : 
                # read data
                try : 
                    r: Packet = self.deviceValve.podDevice.ReadPODpacket()
                except : 
                    continue # bad checksum / corrupted data 
                # check stop condition 
                if(r.rawPacket == stopAt) : 
                    return
                # save binary packet data
                if( not isinstance(r,PacketStandard)) : # ignore standard packets
                    data[i] = r
                    i += 1 # update looping condition 
            # get times 
            nextTime = currentTime + (round(time.time(),9) - ti)
            # update trackers before looping again
            self.timestamps = np.linspace( # evenly spaced numbers over interval.
                currentTime,    # start time
                nextTime,       # stop time
                self.sampleRate # number of items 
            ).tolist()
            self.data = data
            currentTime = nextTime
            self.numFlowLoops += 1

            
    @staticmethod
    def TestDeviceConnection(pod: Pod, pingCmd:str|int='PING') -> bool :
        """Tests if a POD device can be read from or written. Sends a PING command. 

        Args:
            pod (POD_Basics): POD device to read to and write from.
            pingCmd (str | int, optional): Command name or number to ping. Defaults to 'PING'.

        Returns:
            bool: True for successful connection, false otherwise.
        """
        # returns True when connection is successful, false otherwise
        try:
            pod.FlushPort() # clear out any unread packets 
            w: PacketStandard = pod.WritePacket(cmd=pingCmd)
            r: Packet = pod.ReadPODpacket()
        except:   return(False)
        # check that read matches ping write
        if(w.rawPacket==r.rawPacket): return(True)
        return(False)