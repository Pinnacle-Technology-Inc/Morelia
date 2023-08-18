# enviornment imports
import time
from datetime   import datetime
from io         import TextIOWrapper

# local imports
from PodApi.Stream.Drain    import DrainToFile, Drain8206HR, Drain8401HR
from PodApi.Stream          import Bucket
from PodApi.Devices         import Pod8206HR, Pod8401HR

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

        
class DrainToTXT(DrainToFile) :
    
    def __init__(self, dataBucket: Bucket, fileName: str, preampDevice: str|None = None) -> None:
        super().__init__(dataBucket, fileName, preampDevice)
        # check for valid file extension 
        if( DrainToTXT.GetExtension(self.fileName) not in ['.txt', '.csv'] ) : 
            raise Exception('[!] DrainToTXT only accepts .txt or .csv extensions.')
        # determine device in use 
        device = self.dataBucket.dataHose.deviceValve.podDevice
        if(   isinstance(device, Pod8206HR) ) : self.deviceHandle = Drain8206HR()
        elif( isinstance(device, Pod8401HR) ) : self.deviceHandle = Drain8401HR(preampDevice)
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