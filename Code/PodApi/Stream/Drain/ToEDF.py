# local imports
from PodApi.Stream.Drain    import DrainToFile, DrainToTXT
from PodApi.Stream          import Bucket

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class DrainToEDF(DrainToFile) : 
    
    def __init__(self, dataBucket: Bucket, fileName: str, preampDevice: str|None = None) -> None:
        super().__init__(dataBucket, fileName, preampDevice)
        if( DrainToEDF.GetExtension(self.fileName) != '.edf' ) : 
            raise DrainToEDF('[!] DrainToTXT only accepts the .edf extension.')