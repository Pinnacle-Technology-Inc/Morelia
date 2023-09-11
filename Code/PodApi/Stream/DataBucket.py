# enviornment imports
import time
from threading import Thread
from queue import Queue

# local imports
from PodApi.Devices import Pod8206HR, Pod8401HR
from PodApi.Packets import Packet
from PodApi.Stream  import Hose

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Bucket : 
    """Class to collect the data and timestamps when streaming from a POD device.
    
    Attributes:
        dataHose (Hose): Hose used to stream data from the POD device.
        drops (Queue[ tuple[ list[float], list[Packet|None] ] ]): Queue of the drops \
            (timestamps and data) collected from the Hose.
        totalDropsCollected (int): Counts the total number of Drops collected from the Hose.
        isCollecting (bool): True when collecting drops from the Hose, False otherwise.
    """
    
    def __init__(self, podDevice: Pod8206HR|Pod8401HR, useFilter: bool = True) -> None:
        """Set class instance variables.

        Args:
            podDevice (Pod8206HR | Pod8401HR): POD device to stream data from.
            useFilter (bool): Flag to remove corrupted data and timestamps when True; \
                does not remove points when False. Defaults to True.
        """
        # set instance variables 
        self.dataHose: Hose = Hose(podDevice,useFilter)
        self.drops: Queue[ tuple[ list[float], list[Packet|None] ] ] = Queue() # Each item in queue is a tuple (x,y) with 1 sec of timestamps (x) and data (y) 
        self.totalDropsCollected: int = 0 # rolling counter
        self.isCollecting: bool = False
        
    def EmptyBucket(self) : 
        """Resets the class.
        """
        self.dataHose.EmptyHose()
        # reset all 
        self.drops = Queue()
        self.totalDropsCollected = 0
        self.isCollecting = False
        
    def GetVolumeOfDrops(self) -> int : 
        """Get the number of data drops currently in the queue.

        Returns:
            int: Size of the drops queue.
        """
        return self.drops.qsize()

    def DripDrop(self) -> tuple[ list[float], list[Packet|None] ]: 
        """Dequeues the first point (timestamp, data) in the drops queue.

        Raises:
            Exception: No drops left to dequeue.

        Returns:
            tuple[ list[float], list[Packet|None] ]: Tuple (x,y) with ~1 sec of \
                timestamps (x) and data (y) .
        """
        if(not self.drops.empty() ) :
            return self.drops.get()
        else :
            raise Exception('[!] No drops left to dequeue.')

    def StopCollecting(self) : 
        """Tells the POD device to stop streaming data.
        """
        # signal to stop streaming 
        self.dataHose.StopStream()    

    def StartCollecting(self, duration_sec: float|None = None ) -> Thread : 
        """Start collecting stream data into the Bucket.

        Args:
            duration_sec (float | None, optional): How long to stream data in seconds. Defaults to None.

        Returns:
            Thread: Started Thread for data collection.
        """
        self.EmptyBucket()
        # start streaming data
        self.isCollecting = True
        self.dataHose.StartStream()
        # collect streaming data 
        if(duration_sec == None) : 
            collect: Thread = Thread(target=self._CollectWhileOpen)
        else : 
            collect: Thread = Thread(target=self._CollectForDuration, args=(float(duration_sec),))
        collect.start() 
        return collect # call collect.join() to pause program until thread finishes
    
    def _CollectWhileOpen(self) : 
        """Collect streaming data until the Hose is finished dripping.
        """
        # collect data while the device is streaming 
        while(self.dataHose.isOpen or self._IsDropAvailableInHose()) : 
            # check for new data
            if(self._IsDropAvailableInHose()) :
                self._CollectDrop()
            else : 
                # wait for new data 
                time.sleep(0.1)
        self.isCollecting = False
                  
    def _CollectForDuration(self, duration_sec: float) : 
        """Collect streaming data for a given duration.

        Args:
            duration_sec (float): How long to stream data in seconds.
        """
        # collect data for the duration set
        ti: float = time.time()
        while( (time.time() - ti ) < duration_sec) :
            # check for new data
            if(self._IsDropAvailableInHose()) :
                self._CollectDrop()
            # check if streaming has stopped from external cause
            elif(not self.dataHose.isOpen) : 
                self.isCollecting = False
                return
            # wait for new data 
            else :
                time.sleep(0.1)
        # signal to stop streaming 
        self.StopCollecting()
        # clear out remaining data
        self._CollectWhileOpen()
        
    def _CollectDrop(self) :
        """Adds a point to the drops queue. Each point is a tuple (x,y) of the \
        timestamps list (x) and the data list (y) for one drop (values from \
        ~1 sec of streaming, or the number of values approximatly equal to \
        the sample rate).
        """ 
        # add data to lists 
        self.drops.put( (self.dataHose.timestamps, self.dataHose.data) )
        # increment counter
        self.totalDropsCollected += 1
                
    def _IsDropAvailableInHose(self) -> bool: 
        """Checks if the Hose has any uncollected drops.

        Returns:
            bool: True if there is a drop to be collected, False otherwise.
        """
        return ( self.totalDropsCollected < self.dataHose.numDrops ) 