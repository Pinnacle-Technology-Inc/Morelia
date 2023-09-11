# enviornment imports
from    typing      import Callable, Any
from    threading   import Thread
import  numpy       as     np
import  time

# local imports
from PodApi.Devices     import Pod8206HR, Pod8401HR
from PodApi.Packets     import Packet, PacketStandard
from PodApi.Stream      import Valve

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
        filterMethod (str): Method used to filter out corrupted data. 
        filterInsert (float): Value to replace corrupted data with if using \
            the 'InsertValue' filter method. Defaults to np.nan.
    """
    
    def __init__(self, podDevice: Pod8206HR|Pod8401HR, filterMethod: str = 'DoNothing', filterInsert: float = np.nan) -> None:
        """Set instance variables.

        Args:
            podDevice (Pod8206HR | Pod8401HR): Pod device to stream data from.
            useFilter (bool): Flag to remove corrupted data and timestamps when True; \
                does not remove points when False. Defaults to True.
            filterMethod (str, optional): Method used to filter out corrupted data. \
                Defaults to 'DoNothing'.
            filterInsert (float, optional): Value to replace corrupted data with if using \
                the 'InsertValue' filter method. Defaults to np.nan.
        """
        # properties 
        self.sampleRate   : int   = Hose.GetSampleRate(podDevice)
        self.deviceValve  : Valve = Valve(podDevice)
        self.isOpen       : bool = False
        self.filterMethod : Callable = self.PickFilterMethod(filterMethod)
        self.filterInsert : float = float(filterInsert)
        # drops 
        self.data       : list[Packet|Any] = []
        self.timestamps : list[float] = []
        # counters
        self.numDrops : int = 0
        self.corruptedPoints : int = 0

        
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
        self.deviceValve.EmptyValve()
        # reset to default
        self.data       : list[Packet|None] = []
        self.timestamps : list[float] = []
        self.numDrops   : int = 0
        self.corruptedPoints: int = 0
        self.isOpen = False

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
                except Exception as e : 
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
        if(self._Filter(data,timestamps)) :
            # update trackers before looping again
            self.timestamps = timestamps
            self.data = data
            self.numDrops += 1
        # finish
        return nextTime

    def PickFilterMethod(self, filterMethod: str) : 
        """Set the method used to filter corrupted data when streaming. The filter methods \
        include 'RemoveEntry', 'InsertValue', 'TakePast', 'TakeFuture', or 'DoNothing'.  \
        The default method is 'DoNothing'.

        Args:
            filterMethod (str): Filter method, which can be 'RemoveEntry', 
                'InsertValue', 'TakePast', 'TakeFuture', or 'DoNothing'/other.
        """
        match str(filterMethod) : 
            case 'RemoveEntry'  : return self._Filter_RemoveEntry
            case 'InsertValue'  : return self._Filter_InsertValue
            case 'TakePast'     : return self._Filter_TakePast
            case 'TakeFuture'   : return self._Filter_TakeFuture
            case  _             : return self._Filter_DoNothing
                 
    def SetFilterInsertValue(self, insert: float) : 
        """Sets the value to insert in place of currupted data. This is only used if \ 
        the filter method is 'InsertValue'.

        Args:
            insert (float): Numerical value to insert.
        """
        self.filterInsert : float = float(insert)

    def _Filter(self, data: list[Packet|None], timestamps: list[float]) -> bool : 
        """Searches the data list for corrupted points, and deals with them \
        according to the set filter method. 

        Args:
            data (list[Packet | None]): List of Packets read from the POD device.
            timestamps (list[float]): List of timestamps in seconds for each Packet \
                in the data list. 

        Returns:
            bool: True when the corrupted data is filtered, False otherwise. A list \
                containing only None cannot be filtered.
        """
        # edge case, list cannot contain only None
        if(data.count(None) == len(data)) :
            return False 
        # check if there is any corrupted data
        if(None in data) : 
            # get list of all indices where there is corrupted data
            allIndices = [index for (index, item) in enumerate(data) if item == None]
            for i in allIndices: 
                # fix this datapoint 
                self.filterMethod(i,data,timestamps)
        return True 
            
    def _Filter_RemoveEntry(self, i: int, data: list[Packet|None], timestamps: list[float] ) :
        """Removes a datapoint at index i from the data and timestamps lists.

        Args:
            i (int): Index of corrupted data.
            data (list[Packet | None]): List of Packets read from the POD device.
            timestamps (list[float]): List of timestamps in seconds for each Packet \
                in the data list. 
        """
        # remove item from list
        data.pop(i)
        timestamps.pop(i)
        # update counter
        self.corruptedPoints += 1       

    def _Filter_InsertValue(self, i: int, timestamps: list[float], data: list[Packet|None] ) : 
        """Replaces the data value at index i with a set value (class defaults to np.nan). 

        Args:
            i (int): Index of corrupted data.
            data (list[Packet | None]): List of Packets read from the POD device.
            timestamps (list[float]): List of timestamps in seconds for each Packet \
                in the data list. 
        """
        # set value to default
        data[i] = self.filterInsert
        # update counter
        self.corruptedPoints += 1
        
    def _Filter_TakePast(self, i: int, data: list[Packet|None], timestamps: list[float] )  :
        """Replaces the data value at index i with the previous Packet. If the index points \
        to the first value in the data list, the data will be replaced with the next Packet instead.

        Args:
            i (int): Index of corrupted data.
            data (list[Packet | None]): List of Packets read from the POD device.
            timestamps (list[float]): List of timestamps in seconds for each Packet \
                in the data list. 
        """
        # i is not the first value in the list 
        if(i>0) : 
            # data at previous index will never be None as data.index(None) finds the first instance of None
            data[i] = data[i-1]
            # update counter
            self.corruptedPoints += 1
        # i is the first value in list. Cannot take a past value.
        else : 
            self._Filter_TakeFuture(i,data,timestamps)
    
    def _Filter_TakeFuture(self, i: int, data: list[Packet|None], timestamps: list[float] ) :
        """Replaces the data value at index i with the next Packet. If the index points \
        to the last value in the data list, the data will be replaced with the previous \
        Packet instead. If there are multiple currupted points in a row (data value is \
        None), then all points will be replaced with the same future Packet.

        Args:
            i (int): Index of corrupted data.
            data (list[Packet | None]): List of Packets read from the POD device.
            timestamps (list[float]): List of timestamps in seconds for each Packet \
                in the data list. 
        """
        # get maximum index from the list
        iMax = len(data) - 1
        # i is not the last value in list 
        if(i < iMax ) : 
            # index of next value
            iGood = i + 1
            # search for non-corrupted packet 
            while( iGood <= iMax and data[iGood] == None ) : 
                iGood += 1
            # edge case, no good future data to take 
            if(iGood > iMax ) : 
                self._Filter_TakePast(i,data,timestamps)
            # fix corrupted packets
            goodData: Packet = data[iGood]
            while(iGood - i > 0) : 
                data[i] = goodData
                i += 1
                # update counter
                self.corruptedPoints += 1
        # i is the last value in the list. Cannot take a future value.
        else :
            self._Filter_TakePast(i,data,timestamps)
    
    def _Filter_DoNothing(self, i: int, data: list[Packet|None], timestamps: list[float] ) : 
        """Does nothing to the data and timestamps lists.

        Args:
            i (int): Index of corrupted data.
            data (list[Packet | None]): List of Packets read from the POD device.
            timestamps (list[float]): List of timestamps in seconds for each Packet \
                in the data list. 
        """
        # dont make any changes to the lists 
        pass