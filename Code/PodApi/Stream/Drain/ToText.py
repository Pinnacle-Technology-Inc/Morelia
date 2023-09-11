# enviornment imports
import time
from datetime   import datetime
from io         import TextIOWrapper

# local imports
from PodApi.Stream.Drain    import DrainToFile
from PodApi.Stream          import Bucket

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

        
class DrainToTXT(DrainToFile) :
    """Class to to drain, or save, the data drops collected by a Bucket into a text file.

    Attributes:
        file (TextIOWrapper|None): Text file where streaming data is saved to.
    """
    
    def __init__(self, dataBucket: Bucket, fileName: str, preampDevice: str|None = None) -> None:
        """Set class instance variables.

        Args:
            dataBucket (Bucket): Bucket to collect streaming data.
            fileName (str): Name (with optional file path) of the file to save data to.
            preampDevice (str | None, optional): Optional preamplifier for the 8401-HR. Defaults to None.

        Raises:
            Exception: DrainToTXT only accepts '.txt' or '.csv' extensions.
        """
        super().__init__(dataBucket, fileName, preampDevice)
        # check for valid file extension 
        if( DrainToTXT.GetExtension(self.fileName) not in ['.txt', '.csv'] ) : 
            raise Exception('[!] DrainToTXT only accepts \'.txt\' or \'.csv\' extensions.')
        # init
        self.file: TextIOWrapper|None = None
    
    def OpenFile(self) : 
        """Opens and initializes a file using the fileName to save data to. 
        """
        # open file and write column names 
        self.file = open(self.fileName, 'w')
        # write time
        self.file.write(self._GetTimeHeader()) 
        # columns names
        self.file.write(self.deviceHandler.GetDeviceColNames())

    def CloseFile(self) : 
        """Closes the file that data is saved to.
        """
        if(self.file != None) : self.file.close()
        
    def DrainDropToFile(self) : 
        """Write one drop of data to the save file.
        """
        # checks 
        if(self.dataBucket.GetVolumeOfDrops() <= 0 ) : return
        if(self.file == None) : return
        # get data 
        timestamps, data = self.dataBucket.DripDrop()
        df = self.deviceHandler.DropToDf(timestamps, data)
        # remove column names from csv table string by splitting at first '\n'
        self.file.write( df.to_csv().split('\n',1) [1] )
        
    @staticmethod
    def _GetTimeHeader() -> str : 
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