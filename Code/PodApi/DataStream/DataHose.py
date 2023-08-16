# enviornment imports
from   threading import Thread
import numpy as np
import time

# local imports
from PodApi.Devices     import Pod8206HR, Pod8401HR
from PodApi.Packets     import Packet, PacketStandard
from PodApi.DataStream  import Valve

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Hose : 
    """Collects streaming data from an 8206-HR or 8401-HR POD device. The data \
    and timestamps are updated about every 1 second when streaming.
    
    Attributes: 
        sampleRate (int): Sample rate of the POD device.
        deviceValve (Valve): To open or close the data stream. 
        data (list[Packet|None]): List of streaming binary data packets. 
        timestamps (list[float]: List of timestamps for each data packet.
        numDrops (int): Number of drops, or number of times the data and \
            timestamps have been updated. 
        corruptedPointsRemoved (int): Total number of corrupted data points \
            removed from the data and timestamps lists.
        useFilter (bool): Flag to remove corrupted data and timestamps when True; \
            does not remove points when False. Defaults to True.
    """
    
    def __init__(self, podDevice: Pod8206HR|Pod8401HR, useFilter: bool = True) -> None:
        """Set instance variables.

        Args:
            podDevice (Pod8206HR | Pod8401HR): Pod device to stream data from.
        """
        # set variables 
        self.sampleRate : int   = Hose.GetSampleRate(podDevice)
        self.deviceValve: Valve = Valve(podDevice)
        self.data       : list[Packet|None] = []
        self.timestamps : list[float] = []
        self.numDrops   : int = 0
        self.corruptedPointsRemoved: int = 0
        self.useFilter  : bool = bool(useFilter)
        self.isOpen     : bool = False
        
    def SetUseFilter(self, useFilter: bool) : 
        """Sets the flag to remove corrupted data and timestamps when True; \
        does not remove points when False.

        Args:
            useFilter (bool): True or False.
        """
        self.useFilter = bool(useFilter)
        
    @staticmethod
    def GetSampleRate(podDevice: Pod8206HR|Pod8401HR) -> int : 
        """Writes a command to the POD device to get its sample rate in Hz.

        Args:
            podDevice (Pod8206HR | Pod8401HR): POD device to get the sample rate for.

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
        # ----------------------------------------------------------------------------------------------
        # NOTE both 8206HR and 8401HR use the same command to start streaming. 
        # If there is a new device that uses a different command, add a method 
        # to check what type the device is (i.e isinstance(podDevice, PodClass)) 
        # and set the self.stream* instance variables accordingly.
        podDevice._commands.ValidateCommand('GET SAMPLE RATE')        
        if(not podDevice.TestConnection()) : 
            raise Exception('[!] Could not connect to this POD device.')
        pkt: PacketStandard = podDevice.WriteRead('GET SAMPLE RATE')
        return int(pkt.Payload()[0]) 

    def EmptyHose(self) : 
        # reset to default
        self.data       : list[Packet|None] = []
        self.timestamps : list[float] = []
        self.numDrops   : int = 0
        self.corruptedPointsRemoved: int = 0

    def StartStream(self) : 
        """Start a thread to start streaming data from the POD device.
        """
        # initialize class instance
        self.EmptyHose()
        self.isOpen = True
        # threading 
        stream = Thread( target = self._Flow )
        # start streaming (program will continue until .join() or streaming ends)
        stream.start() 
        return(stream)
            
    def StopStream(self) : 
        """Writes a command to the POD device to stop streaming data.
        """
        # stop streaming
        self.deviceValve.Close()
        
    def _Flow(self) : 
        """Streams data from the POD device. The data drops about every 1 second. \
        Streaming will continue until a "stop streaming" packet is recieved. 
        """
        # initialize       
        stopAt: bytes = self.deviceValve.GetStopBytes()
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
                    drip: Packet = self.deviceValve.Drip()
                    # check stop condition 
                    if(drip.rawPacket == stopAt) : # NOTE this is only exit for while(True) 
                        # finish up
                        currentTime = self._Drop(currentTime, ti, data)
                        self.isOpen = False
                        return 
                    # save binary packet data and ignore standard packets
                    if( not isinstance(drip,PacketStandard)) : 
                        data[i] = drip
                        i += 1 # update looping condition 
                except : 
                    # corrupted data here, leave None in data[i]
                    i += 1 # update looping condition          
            currentTime = self._Drop(currentTime, ti, data)

    def _Drop(self, currentTime: float, ti: float, data: list[Packet|None]) -> float : 
        """Updates the instance variables that store the streaming data. \
        The data drops about every 1 second.

        Args:
            currentTime (float): Current start time in seconds.
            ti (float): Computer clock time at the start of the ~1 second drop. 
            data (list[Packet | None]): Packets recieved when streaming.

        Returns:
            float: updated current time in seconds for the next drop.
        """
        # get times 
        nextTime = currentTime + (round(time.time(),9) - ti)
        timestamps: list[float] = np.linspace( # evenly spaced numbers over interval.
            currentTime,    # start time
            nextTime,       # stop time
            self.sampleRate # number of items 
        ).tolist()
        # clean out corrupted data
        if(self.useFilter) : 
            self._Filter(data,timestamps)
        # update trackers before looping again
        self.timestamps = timestamps
        self.data = data
        self.numDrops += 1
        # finish
        return nextTime
    
    def _Filter(self, data: list[Packet|None], timestamps: list[float]) : 
        """Removes any corrupted points from the data and timestamp lists.

        Args:
            data (list[Packet | None]): List of Packets recieved when streaming or None for corrupted data.
            timestamps (list[float]): Timestamp in seconds of each packet.
        """
        # remove all corrupted data from lists
        while(None in data) : 
            # find where None is in the data list
            i = data.index(None)
            # remove data and timestamp where there is corrupted data
            data.pop(i)
            timestamps.pop(i)
            # update counter
            self.corruptedPointsRemoved += 1