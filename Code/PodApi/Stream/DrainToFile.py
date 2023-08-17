# enviornment imports
import os   
from pathlib import Path
from datetime import datetime
import time
from io import TextIOWrapper

# local imports
from PodApi.Stream import Bucket
from PodApi.Devices import Pod8206HR, Pod8401HR

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
    
    def OpenFile(self) : 
        pass
    
    def DrainDropToFile(self) : 
        pass
    
###############################################
        
class DrainToTXT(DrainToFile) :
    
    def __init__(self, dataBucket: Bucket, fileName: str, preampDevice: str|None = None) -> None:
        super().__init__(dataBucket, fileName, preampDevice)
        if( DrainToTXT.GetExtension(self.fileName) not in ['.txt', '.csv'] ) : 
            raise Exception('[!] DrainToTXT only accepts .txt or .csv extensions.')
        self.file: TextIOWrapper|None = None
    
    def OpenFile(self) : 
        # open file and write column names 
        self.file = open(self.fileName, 'w')
        # write time
        self.file.write(self._GetTimeHeader_forTXT()) 
        # columns names
        self.file.write(self._GetColNames())

    def _GetColNames(self) -> str : 
        device = self.dataBucket.dataHose.deviceValve.podDevice
        print(type(device))
        if( isinstance(device, Pod8206HR) ) : 
            return ('Time,TTL,CH0,CH1,CH2\n')
        if( isinstance(device, Pod8401HR)) : 
            cols = 'Time,'
            if(self.preampDevice != None and Pod8401HR.IsPreampDeviceSupported(self.preampDevice)) : 
                channelNames = Pod8401HR.GetChannelMapForPreampDevice(str(self.preampDevice)).values()
                for label in channelNames : 
                    if(label!='NC') : # exclude no-connects 
                        cols += str(label) + ','
            else : 
                cols += 'A,B,C,D,'
            cols += 'Analog EXT0,Analog EXT1,Analog TTL1,Analog TTL2,Analog TTL3,Analog TTL4\n'
            return cols
        raise Exception('[!] POD Device is not supported.')
            
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

class DrainToEDF(DrainToFile) : 
    
    def __init__(self, dataBucket: Bucket, fileName: str, preampDevice: str|None = None) -> None:
        super().__init__(dataBucket, fileName, preampDevice)
        if( DrainToTXT.GetExtension(self.fileName) != '.edf' ) : 
            raise DrainToEDF('[!] DrainToTXT only accepts the .edf extension.')