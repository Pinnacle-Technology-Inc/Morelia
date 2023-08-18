# enviornment imports
import pandas as pd

# local imports
from PodApi.Devices import Pod8401HR
from PodApi.Packets import Packet, PacketBinary4, PacketBinary5

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class DrainDeviceHandler() : # interface
    
    def GetDeviceColNames(self) -> str : 
        pass
    
    def GetDeviceColNamesList(self) -> list[str] : 
        pass
    
    def DropToDf(self, timestamps: list[float], data: list[Packet | None]) -> pd.DataFrame : 
        pass
        
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
    
class Drain8401HR(DrainDeviceHandler) :
    
    def __init__(self, preampDevice: str = None) -> None:
        super().__init__()
        self.preampDevice: str|None = preampDevice

    def GetDeviceColNames(self) -> str :
        cols = self.GetDeviceColNamesList()
        cols.remove('NC')
        return ','.join(cols) + '\n'
    
    def GetDeviceColNamesList(self) -> list[str] : 
        cols = ['Time']
        if(self.preampDevice != None and Pod8401HR.IsPreampDeviceSupported(self.preampDevice)) : 
            for label in Pod8401HR.GetChannelMapForPreampDevice(str(self.preampDevice)).values() : 
                cols.append(label)
        else : 
            cols += ['A','B','C','D']
        cols += ['Analog EXT0','Analog EXT1','Analog TTL1','Analog TTL2','Analog TTL3','Analog TTL4']
        return cols
                    
    def DropToDf(self, timestamps: list[float], data: list[Packet | None]) -> pd.DataFrame : 
        cols = self.GetDeviceColNamesList()
        dfPrep = { cols[0] : timestamps }
        # channels
        for idx,ch in zip([1,2,3,4], ['A','B','C','D']) : 
            if(cols[idx] != 'NC') : 
                dfPrep[cols[idx]] = [ pkt.Channel(ch) if (isinstance(pkt, PacketBinary5)) else None for pkt in data]
        # EXT
        for idx,ext in zip([5,6], [0,1]) : 
            dfPrep[cols[idx]] = [ pkt.AnalogEXT(ext) if (isinstance(pkt, PacketBinary5)) else None for pkt in data]
        # TTL
        for idx,ttl in zip([7,8,9,10], [1,2,3,4]) : 
            dfPrep[cols[idx]] = [ pkt.AnalogTTL(ttl) if (isinstance(pkt, PacketBinary5)) else None for pkt in data]
        # build df 
        return pd.DataFrame(dfPrep)
