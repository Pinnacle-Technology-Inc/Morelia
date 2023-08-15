# local imports
from PodApi.Devices import Pod8206HR, Pod8401HR
from PodApi.Packets import Packet, PacketStandard, PacketBinary4, PacketBinary5
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
        
        self.dataHose: Hose = Hose(podDevice,useFilter)
        
        self.allData: list[list[Packet|None]] = []
        self.allTimestamps: list[list[float]] = []
                
                
    @staticmethod
    def Split(data : list[Packet|None]) : 
        if(isinstance(data[0], PacketBinary4)) : 
            return Bucket.SplitBinary4(data)
        if(isinstance(data[0], PacketBinary5)) : 
            return Bucket.PacketBinary5(data)
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