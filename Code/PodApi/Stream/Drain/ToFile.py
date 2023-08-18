
# enviornment imports
import os   

# local imports
from PodApi.Stream import Bucket

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
            raise Exception('[!] dataBucket must be of Bucket type.')
        self.dataBucket: Bucket = dataBucket
        self.fileName: str = str(fileName)
        self.preampDevice: str|None = preampDevice

    @staticmethod
    def GetExtension(fileName) : 
        return os.path.splitext(fileName)[1]
    
    # interface methods to implement 
    def OpenFile(self) : pass
    def CloseFile(self) : pass
    def DrainDropToFile(self) : pass
    