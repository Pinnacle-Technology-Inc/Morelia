# enviornment imports
import pandas as pd

# local imports
from PodApi.Packets import Packet, PacketBinary4
from PodApi.Stream.Drain.PodHandler import DrainDeviceHandler

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"
        
######################################################
        
class Drain8206HR(DrainDeviceHandler) :
    
    def GetDeviceColNames(self) -> str :
        return ','.join(self.GetDeviceColNamesList()) + '\n'
    
    def GetDeviceColNamesList(self) -> list[str] : 
        return ['Time','CH0','CH1','CH2']
    
    def DropToDf(self, timestamps: list[float], data: list[Packet | None]) -> pd.DataFrame : 
        return pd.DataFrame({
            'Time' : timestamps,
            # 'TTL'  : [ pkt.Ttl() if (isinstance(pkt, PacketBinary4)) else None for pkt in data],
            'CH0'  : [ pkt.Ch(0) if (isinstance(pkt, PacketBinary4)) else None for pkt in data],
            'CH1'  : [ pkt.Ch(1) if (isinstance(pkt, PacketBinary4)) else None for pkt in data],
            'CH2'  : [ pkt.Ch(2) if (isinstance(pkt, PacketBinary4)) else None for pkt in data]
        })