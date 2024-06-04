# enviornment imports
import time
from threading import Thread

# local imports
from Morelia.Stream.Collect import Bucket
from Morelia.Stream.Drain import DrainToFile, DrainToTXT, DrainToEDF

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class DrainBucket : 
    """This class is used to save the streaming data from a POD device that was \
    collected by a Bucket into a file. 
    
    Attributes: 
        self.drainToFile (DrainToTXT, DrainToEDF): Class to to drain the data drops \
            collected by a Bucket into a text or EDF file.
    """

    def __init__(self, dataBucket: Bucket, fileName: str, preampDevice: str|None = None) -> None:
        """Set class instance variables.

        Args:
            dataBucket (Bucket): Bucket to collect streaming data.
            fileName (str): Name (with optional file path) of the file to save data to.
            preampDevice (str | None): Optional preamplifier for the 8401-HR. Defaults to None.

        Raises:
            Exception: File extension is not supported.
        """
        ext: str  = DrainToFile.GetExtension(fileName)
        if( ext in ['.txt', '.csv']) : 
            self.drainToFile: DrainToTXT = DrainToTXT(dataBucket, fileName, preampDevice)
        elif(ext == '.edf') : 
            self.drainToFile: DrainToEDF = DrainToEDF(dataBucket, fileName, preampDevice)
        else : 
            raise Exception('[!] File extension '+str(ext)+' is not supported.')    
           
    def IsDataAvailable(self) -> bool : 
        """Checks if data is available in the Bucket. 

        Returns:
            bool: True if there are any drops in the Bucket, False otherwise.
        """
        return ( self.drainToFile.dataBucket.GetVolumeOfDrops() <= 0 )
    
    def IsCollecting(self) -> bool : 
        """Checks if the Bucket is collected data from the Hose.

        Returns:
            bool: True if the Bucket is collecting data, False otherwise.
        """
        return ( self.drainToFile.dataBucket.isCollecting )
           
    def DrainBucketToFile(self, timeout_sec: float=10.0, sleep: float=0.25) -> Thread : 
        """Starts a thread that starts draining data drops into the save file. 

        Args:
            timeout_sec (float, optional): Quit saving data if no new data is recieved \
                after timeout_sec time (in seconds). Defaults to 10.0.
            sleep (float, optional): Time duration in seconds to wait for the Bucket to \
                collect more data before checking agian. Defaults to 0.25.

        Returns:
            Thread: Started thread where data is being saved to a file.
        """
        t: Thread = Thread(target=self._ThreadedDrainBucketToFile, args=(timeout_sec,sleep))
        t.start()
        return t 
           
    def _ThreadedDrainBucketToFile(self, timeout_sec: float=10.0, sleep: float=0.25) :
        """Opens a save file and starts saving data to it. The file is updated about every 1 sec. \
        After the POD device stops streaming data, the file will close.

        Args:
            timeout_sec (float, optional): Quit saving data if no new data is recieved \
                after timeout_sec time (in seconds). Defaults to 10.0.
            sleep (float, optional): Time duration in seconds to wait for the Bucket to \
                collect more data before checking agian. Defaults to 0.25.
        """
        timeoutTicker: float = 0
        # open file to save streaming data to 
        self.drainToFile.OpenFile()
        # loop while the pod device is streaming 
        while(self.drainToFile.dataBucket.isCollecting) : 
            try: 
                timeoutTicker = self._DrainDropToFile(timeoutTicker,timeout_sec,sleep)
            except Exception as e: 
                print(e)
                break # force exit loop 
        # finish 
        self.drainToFile.CloseFile()
    
    def _DrainDropToFile(self, timeoutTicker: float, timeout_sec: float=10.0, sleep: float=0.25) -> float : 
        """When data is available in the bucket, write one drop of data to the save file. 

        Args:
            timeoutTicker (float): Counts the amout of time passed since the last drop was recieved.
            timeout_sec (float, optional): Quit saving data if no new data is recieved \
                after timeout_sec time (in seconds). Defaults to 10.0.
            sleep (float, optional): Time duration in seconds to wait for the Bucket to \
                collect more data before checking agian. Defaults to 0.25.

        Raises:
            Exception: Timeout: no data found to be saved to file.

        Returns:
            float: Updated timeoutTicker.
        """
        # delay if there is no data to save
        if(self.IsDataAvailable()) : 
            # stop saving data if no drops
            if(timeoutTicker == timeout_sec) : 
                raise Exception('[!] Timeout ('+str(timeoutTicker)+'sec'+'): no data found to be saved to file.')
            # wait for some time to let the bucket to collect
            time.sleep(sleep)
            return timeoutTicker+sleep
        # otherwise, save data to file 
        else:
            self.drainToFile.DrainDropToFile()
            return 0 # reset ticker 
                        