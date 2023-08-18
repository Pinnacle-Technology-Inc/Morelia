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

class DrainToEDF(DrainToFile) : 
    
    def __init__(self, dataBucket: Bucket, fileName: str, preampDevice: str|None = None) -> None:
        """Set class instance variables.

        Args:
            dataBucket (Bucket): Bucket to collect streaming data.
            fileName (str): Name (with optional file path) of the file to save data to.
            preampDevice (str | None, optional): Optional preamplifier for the 8401-HR. Defaults to None.

        Raises:
            DrainToEDF: DrainToTXT only accepts the '.edf' extension.
        """
        super().__init__(dataBucket, fileName, preampDevice)
        if( DrainToEDF.GetExtension(self.fileName) != '.edf' ) : 
            raise DrainToEDF('[!] DrainToTXT only accepts the \'.edf\' extension.')
        
    # TODO this class 