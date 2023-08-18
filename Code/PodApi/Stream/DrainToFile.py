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
           
    def StartDrainingToFile():
        pass
        # check if data is streaming or if data available
        # deque a drop
        # save drop to file
        # loop until streaming is done 