# enviornment imports
import pandas as pd

# local imports
from PodApi.Packets import Packet
from PodApi.Stream  import Bucket

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class DrainDeviceHandler() : # interface class
    
    @staticmethod
    def GetPodFromBucket(bkt: Bucket) : 
        return bkt.dataHose.deviceValve.podDevice
    
    # interface methods to implement 
    def GetDeviceColNames(self) -> str : pass
    def GetDeviceColNamesList(self) -> list[str] : pass
    def DropToDf(self, timestamps: list[float], data: list[Packet | None]) -> pd.DataFrame : pass