
# enviornment imports
import os   

# local imports
from PodApi.Devices import Pod8206HR, Pod8401HR
from PodApi.Stream  import Bucket
from PodApi.Stream.Drain.PodHandler import DrainDeviceHandler, Drain8206HR, Drain8401HR

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class DrainToFile : # interface class
    
    def __init__(self, dataBucket: Bucket, fileName: str, preampDevice: str|None = None) -> None:
        if(not isinstance(dataBucket, Bucket)) : 
            raise Exception('[!] The dataBucket must be of Bucket type.')
        self.dataBucket     : Bucket    = dataBucket
        self.fileName       : str       = str(fileName)
        self.preampDevice   : str|None  = preampDevice
        self.deviceHandle   : Drain8206HR|Drain8401HR = DrainToFile.GetHandlerForBucket(dataBucket,preampDevice)

    @staticmethod
    def GetHandlerForBucket(bkt: Bucket, preampDevice:str|None=None) : 
        # pick handler according to POD device type
        device = DrainDeviceHandler.GetPodFromBucket(bkt)
        if(   isinstance(device, Pod8206HR) ) : return Drain8206HR()
        elif( isinstance(device, Pod8401HR) ) : return Drain8401HR(preampDevice)
        else: raise Exception('[!] POD Device is not supported.')

    @staticmethod
    def GetExtension(fileName) : 
        return os.path.splitext(fileName)[1]
    
    # interface methods to implement 
    def OpenFile(self) : pass
    def CloseFile(self) : pass
    def DrainDropToFile(self) : pass
    