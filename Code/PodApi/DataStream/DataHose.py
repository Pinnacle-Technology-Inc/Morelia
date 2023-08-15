# enviornment imports
from threading import Thread
import numpy as np
import time

# local imports
from PodApi.Devices import Pod8206HR, Pod8401HR
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
    
    def __init__(self, podDevice: Pod8206HR|Pod8401HR) -> None:
        # set variables 
        self.sampleRate : int   = Hose.GetSampleRate(podDevice)
        self.deviceValve: Valve = Valve(podDevice)
        self.data       : list[Packet] = []
        self.timestamps : list[float] = []
        self.numDrops   : int = 0
        self.corruptedPointsRemoved: int = 0
        
    @staticmethod
    def GetSampleRate(podDevice: Pod8206HR|Pod8401HR) -> int : 
        # Device  ::: cmd, command name,    args, ret, description
        # ----------------------------------------------------------------------------------------------
        # 8206-HR ::: 100, GET SAMPLE RATE, None, U16, Gets the current sample rate of the system, in Hz
        # 8401-HR ::: 100, GET SAMPLE RATE, None, U16, Gets the current sample rate of the system, in Hz
        # ----------------------------------------------------------------------------------------------
        # NOTE both 8206HR and 8401HR use the same command to start streaming. 
        # If there is a new device that uses a different command, add a method 
        # to check what type the device is (i.e isinstance(podDevice, PodClass)) 
        # and set the self.stream* instance variables accordingly.
        if(not podDevice._commands.ValidateCommand('GET SAMPLE RATE')) : 
            raise Exception('[!] Cannot get the sample rate for this POD device.')
        if(not podDevice.TestConnection()) : 
            raise Exception('[!] Could not connect to this POD device.')
        pkt: PacketStandard = podDevice.WriteRead('GET SAMPLE RATE')
        return int(pkt.Payload()[0]) 

    def StartStream(self) : 
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
            cmd     = self.deviceValve.streamCmd,
            payload = self.deviceValve.streamPldStop            )
        currentTime : float = 0.0 
        # start streaming data 
        self.deviceValve.Open()
        while(True) : 
            # initialize
            data: list[Packet|None] = [None] * self.sampleRate
            ti = (round(time.time(),9)) # initial time (sec)
            # read data for one second
            i: int = 0
            while (i < self.sampleRate) : # operates like 'for i in range(sampleRate)'
                try : 
                    # read data (vv exception raised here if bad checksum vv)
                    r: Packet = self.deviceValve.podDevice.ReadPODpacket()
                    # check stop condition 
                    if(r.rawPacket == stopAt) : # NOTE this is only exit for while(True) 
                        # finish up
                        currentTime = self._Drop(currentTime, ti, data)
                        return 
                    # save binary packet data and ignore standard packets
                    if( not isinstance(r,PacketStandard)) : 
                        data[i] = r
                        i += 1 # update looping condition 
                except : 
                    # corrupted data here, leave None in data[i]
                    i += 1 # update looping condition          
            currentTime = self._Drop(currentTime, ti, data)

    def _Drop(self, currentTime: float, ti: float, data: list[Packet|None]) : 
        # get times 
        nextTime = currentTime + (round(time.time(),9) - ti)
        timestamps: list[float] = np.linspace( # evenly spaced numbers over interval.
            currentTime,    # start time
            nextTime,       # stop time
            self.sampleRate # number of items 
        ).tolist()
        # clean out corrupted data
        self._Filter(data,timestamps)
        # update trackers before looping again
        self.timestamps = timestamps
        self.data = data
        self.numDrops += 1
        # finish
        return nextTime
    
    def _Filter(self, data: list[Packet|None], timestamps: list[float]) : 
        # remove all corrupted data from lists
        while(None in data) : 
            # find where None is in the data list
            i = data.index(None)
            # remove data and timestamp where there is corrupted data
            data.pop(i)
            timestamps.pop(i)
            # update counter
            self.corruptedPointsRemoved += 1