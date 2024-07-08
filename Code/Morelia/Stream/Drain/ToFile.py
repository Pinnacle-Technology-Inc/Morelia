
# enviornment imports
import os   

# local imports
from Morelia.Devices             import Pod8206HR, Pod8401HR, Pod8274D
from Morelia.Stream.Collect      import Bucket
from Morelia.Stream.PodHandler   import DrainDeviceHandler, Drain8206HR, Drain8401HR, Drain8274D

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class DrainToFile : # interface class
    """Interface class to to drain, or save, the data drops collected by a Bucket into a file.
    
    Attributes: 
        dataBucket (Bucket): Bucket to collect streaming data.
        fileName (str): Name (with optional file path) of the file to save data to.
        preampDevice (str | None): Optional preamplifier for the 8401-HR.
        deviceHandler (Drain8206HR | Drain8401HR | Drain8274D): Class to help handle different POD device types.
    """
    
    def __init__(self, dataBucket: Bucket, fileName: str, preampDevice: str|None = None) -> None:
        """Set class instance variables.

        Args:
            dataBucket (Bucket): Bucket to collect streaming data.
            fileName (str): Name (with optional file path) of the file to save data to.
            preampDevice (str | None, optional): Optional preamplifier for the 8401-HR. Defaults to None.

        Raises:
            Exception: The dataBucket must be of Bucket type.
        """
        if(not isinstance(dataBucket, Bucket)) : 
            raise Exception('[!] The dataBucket must be of Bucket type.')
        self.dataBucket     : Bucket    = dataBucket
        self.fileName       : str       = str(fileName)
        self.preampDevice   : str|None  = preampDevice
        self.deviceHandler  : Drain8206HR|Drain8401HR|Drain8274D = DrainToFile.GetHandlerForBucket(dataBucket,preampDevice)
        
        
    @staticmethod
    def GetHandlerForBucket(bkt: Bucket, preampDevice:str|None=None) -> Drain8206HR|Drain8401HR|Drain8274D: 
        """Selects the proper POD device handler for a given Bucket.

        Args:
            bkt (Bucket): Bucket to collect streaming data.
            preampDevice (str | None, optional): Optional preamplifier for the 8401-HR. Defaults to None.

        Raises:
            Exception: POD Device is not supported.

        Returns:
            Drain8206HR | Drain8401HR | Drain8274D : POD Device Handler.
        """
        # pick handler according to POD device type
        device = DrainDeviceHandler.GetPodFromBucket(bkt)
        if(   isinstance(device, Pod8206HR) ) : return Drain8206HR()
        elif( isinstance(device, Pod8401HR) ) : return Drain8401HR(preampDevice)
        elif( isinstance(device, Pod8274D) )  : return Drain8274D()
        else: raise Exception('[!] POD Device is not supported.')

    @staticmethod
    def GetExtension(fileName: str) -> str: 
        """Gets the extension from a file, such as '.txt', '.csv', '.edf', or '.pvfs'.

        Args:
            fileName (str): Name of the file with an extension.

        Returns:
            str: File extension.
        """
        return os.path.splitext(fileName)[1]
    
    # vvvvv      interface methods to implement      vvvvv
    
    def OpenFile(self) : 
        """Opens and initializes a file using the fileName to save data to. 
        """
        pass
    
    def CloseFile(self) : 
        """Closes the file that data is saved to.
        """
        pass
    
    def DrainDropToFile(self) : 
        """Write one drop of data to the save file.
        """
        pass
    