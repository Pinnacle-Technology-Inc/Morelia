# enviornment imports
import time
from threading import Thread
from queue import Queue

# local imports
from PodApi.Devices import Pod8206HR, Pod8401HR
from PodApi.Packets import Packet, PacketBinary4, PacketBinary5
from PodApi.DataStream import Hose

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Bucket : 
    
    def __init__(self, podDevice: Pod8206HR|Pod8401HR, useFilter: bool = True) -> None:
        # set instance variables 
        self.dataHose: Hose = Hose(podDevice,useFilter)
        self.drops: Queue[ tuple[ list[float], list[Packet|None] ] ] = Queue() # Each item in queue is a tuple with 1 sec of timestamps and data. 
        self.totalDropsCollected: int = 0 # rolling counter

    def GetNumberOfDrops(self) -> int : 
        return self.drops.qsize()

    def DequeueDrop(self) -> tuple[ list[float], list[Packet|None] ]: 
        if(not self.drops.empty() ) :
            return self.drops.get()
        else :
            raise Exception('[!] No drops left to dequeue.')

    def EmptyBucket(self) : 
        # reset all 
        self.dataHose.EmptyHose()
        self.drops = Queue()
        self.totalDropsCollected = 0
        
    def StopCollecting(self) : 
        # signal to stop streaming 
        self.dataHose.StopStream()    

    def StartCollecting(self, duration_sec: float|None = None ) -> Thread : 
        self.EmptyBucket()
        # start streaming data
        self.dataHose.StartStream()
        # collect streaming data 
        if(duration_sec == None) : 
            collect: Thread = Thread(target=self._CollectWhileOpen)
        else : 
            collect: Thread = Thread(target=self._CollectForDuration, args=(float(duration_sec),))
        collect.start()
        return collect
    
    def _CollectWhileOpen(self) : 
        # collect data while the device is streaming 
        while(self.dataHose.isOpen) : 
            # check for new data
            if(self._IsDropAvailable()) :
                self._CollectDrop()
            else : 
                # wait for new data 
                time.sleep(0.25)
                  
    def _CollectForDuration(self, duration_sec: float) : 
        # collect data for the duration set
        ti: float = time.time()
        while( (time.time() - ti ) < duration_sec) :
            # check for new data
            if(self._IsDropAvailable()) :
                self._CollectDrop()
            else : 
                # check if streaming has stopped
                if(not self.dataHose.isOpen) : return
                # wait for new data 
                time.sleep(0.25)
        # signal to stop streaming 
        self.StopCollecting()
        # clear out remaining data
        while(self._IsDropAvailable()) : 
            self._CollectDrop()
        
    def _CollectDrop(self) : 
        # add data to lists 
        self.drops.put( (self.dataHose.timestamps, self.dataHose.data) )
        # increment counter
        self.totalDropsCollected += 1
                
    def _IsDropAvailable(self) -> bool: 
        return ( self.totalDropsCollected < self.dataHose.numDrops ) 
                
    @staticmethod
    def Split(data : list[Packet|None]) : 
        if(isinstance(data[0], PacketBinary4)) : 
            return Bucket.SplitBinary4(data)
        if(isinstance(data[0], PacketBinary5)) : 
            return Bucket.SplitBinary5(data)
        raise Exception('[!] Packet must be a binary 4 or 5 to be split.')
    
    @staticmethod
    def SplitBinary4(data : list[PacketBinary4|None]) : 
        return [    [ None if (pkt == None) else pkt.packetNumber   for pkt in data],
                    [ None if (pkt == None) else pkt.ttl            for pkt in data],
                    [ None if (pkt == None) else pkt.ch0            for pkt in data],
                    [ None if (pkt == None) else pkt.ch1            for pkt in data],
                    [ None if (pkt == None) else pkt.ch2            for pkt in data]    ]

    @staticmethod
    def SplitBinary5(data : list[PacketBinary5|None]) : 
        return [    [ None if (pkt == None) else pkt.packetNumber   for pkt in data],
                    [ None if (pkt == None) else pkt.status         for pkt in data],
                    [ None if (pkt == None) else pkt.channels       for pkt in data],
                    [ None if (pkt == None) else pkt.aEXT0          for pkt in data],
                    [ None if (pkt == None) else pkt.aEXT1          for pkt in data],
                    [ None if (pkt == None) else pkt.aTTL1          for pkt in data],
                    [ None if (pkt == None) else pkt.aTTL2          for pkt in data],
                    [ None if (pkt == None) else pkt.aTTL3          for pkt in data],
                    [ None if (pkt == None) else pkt.aTTL4          for pkt in data]    ]