# enviornment imports
import time
from threading import Thread

# local imports
from PodApi.Stream import Bucket
from PodApi.Stream.Drain import DrainToFile, DrainToTXT, DrainToEDF

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class DrainBucket : 

    def __init__(self, dataBucket: Bucket, fileName: str, preampDevice: str|None = None) -> None:
        ext: str  = DrainToFile.GetExtension(fileName)
        if( ext in ['.txt', '.csv']) : 
            self.drainToFile: DrainToTXT = DrainToTXT(dataBucket, fileName, preampDevice)
        elif(ext == '.edf') : 
            self.drainToFile: DrainToEDF = DrainToEDF(dataBucket, fileName, preampDevice)
        else : 
            raise Exception('[!] Extension '+str(ext)+' is not supported.')    
           
    def IsDataAvailable(self) : 
        return ( self.drainToFile.dataBucket.GetVolumeOfDrops() <= 0 )
    
    def IsCollecting(self) : 
        return ( self.drainToFile.dataBucket.isCollecting )
           
    def DrainBucketToFile(self, timeout_sec: float=10.0, sleep: float=0.25) -> Thread : 
        t: Thread = Thread(target=self._ThreadedDrainBucketToFile, args=(timeout_sec,sleep))
        t.start()
        return t 
           
    def _ThreadedDrainBucketToFile(self, timeout_sec: float=10.0, sleep: float=0.25) :
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
    