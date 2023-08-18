# enviornment imports
import os   
from pathlib import Path
from datetime import datetime
import time
from io import TextIOWrapper
import pandas as pd
from collections.abc import Callable
from typing import Any


# local imports
from PodApi.Stream import Bucket
from PodApi.Devices import Pod8206HR, Pod8401HR
from PodApi.Packets import Packet, PacketBinary4, PacketBinary5

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Drain : 

    def __init__(self, dataBucket: Bucket, fileName: str, preampDevice: str|None = None) -> None:
        ext: str  = DrainToFile.GetExtension(fileName)
        if( ext in ['.txt', '.csv']) : 
            self.drainToFile: DrainToTXT = DrainToTXT(dataBucket, fileName, preampDevice)
        elif(ext == '.edf') : 
            self.drainToFile: DrainToEDF = DrainToEDF(dataBucket, fileName, preampDevice)
        else : 
            raise Exception('[!] Extension '+str(ext)+' is not supported.')    
           
    def StartDrainingToFile():
        pass
        # check if data is streaming or if data available
        # deque a drop
        # save drop to file
        # loop until streaming is done 

###############################################
        
class DrainToFile : # interface class
    
    def __init__(self, dataBucket: Bucket, fileName: str, preampDevice: str|None = None) -> None:
        if(not isinstance(dataBucket, Bucket)) : 
            raise Exception('[!] dataBucket must be of Bucket type.')
        self.dataBucket: Bucket = dataBucket
        self.fileName: str = str(fileName)
        self.preampDevice: str|None = preampDevice

    @staticmethod
    def GetExtension(fileName) : 
        return os.path.splitext(fileName)[1]
    
    # interface methods 
    def OpenFile(self) : pass
    def CloseFile(self) : pass
    def DrainDropToFile(self) : pass
    
###############################################
        

        
class DrainToTXT(DrainToFile) :
    
    def __init__(self, dataBucket: Bucket, fileName: str, preampDevice: str|None = None) -> None:
        super().__init__(dataBucket, fileName, preampDevice)
        # check for valid file extension 
        if( DrainToTXT.GetExtension(self.fileName) not in ['.txt', '.csv'] ) : 
            raise Exception('[!] DrainToTXT only accepts .txt or .csv extensions.')
        # determine device in use 
        device = self.dataBucket.dataHose.deviceValve.podDevice
        if(   isinstance(device, Pod8206HR) ) : self.deviceHandle = DrainToTXT_8206HR()
        elif( isinstance(device, Pod8401HR) ) : self.deviceHandle = DrainToTXT_8401HR(preampDevice)
        else: raise Exception('[!] POD Device is not supported.')
        # init
        self.file: TextIOWrapper|None = None
    
    def DrainDropToFile(self) : 
        # checks 
        if(self.dataBucket.GetNumberOfDrops() <= 0 ) : return
        if(self.file == None) : return
        # get data 
        timestamps, data = self.dataBucket.DequeueDrop()
        df = self.deviceHandle.DropToDf(timestamps, data)
        # remove column names from csv table string by splitting at first '\n'
        self.file.write( df.to_csv().split('\n',1) [1] )
    
    def OpenFile(self) : 
        # open file and write column names 
        self.file = open(self.fileName, 'w')
        # write time
        self.file.write(self._GetTimeHeader_forTXT()) 
        # columns names
        self.file.write(self.deviceHandle.GetDeviceColNames())

    def CloseFile(self) : 
        if(self.file != None) : self.file.close()
        
    @staticmethod
    def _GetTimeHeader_forTXT() -> str : 
        """Builds a string containing the current date and time to be written to the text file header.

        Returns:
            str: String containing the date and time. Each line begins with '#' and ends with a newline.
        """
        # get time 
        now = datetime.now()
        current_time = str(now.time().strftime('%H:%M:%S'))
        # build string 
        header  = (  '#Today\'s date,'+ now.strftime("%d-%B-%Y")) # shows date
        header += ('\n#Time now,'+ current_time) # shows time
        header += ('\n#GMT,'+ time.strftime("%I:%M:%S %p %Z", time.gmtime()) + '\n') # shows GMT time
        return(header)
    
###############################################
    
class DrainToTXT_Device() : # interface
    
    def GetDeviceColNames(self) -> str : 
        pass
    
    def GetDeviceColNamesList(self) -> list[str] : 
        pass
    
    def DropToDf(self, timestamps: list[float], data: list[Packet | None]) -> pd.DataFrame : 
        pass
        
class DrainToTXT_8206HR(DrainToTXT_Device) :
    
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
    
class DrainToTXT_8401HR(DrainToTXT_Device) :
    
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

###############################################

class DrainToEDF(DrainToFile) : 
    
    def __init__(self, dataBucket: Bucket, fileName: str, preampDevice: str|None = None) -> None:
        super().__init__(dataBucket, fileName, preampDevice)
        if( DrainToTXT.GetExtension(self.fileName) != '.edf' ) : 
            raise DrainToEDF('[!] DrainToTXT only accepts the .edf extension.')