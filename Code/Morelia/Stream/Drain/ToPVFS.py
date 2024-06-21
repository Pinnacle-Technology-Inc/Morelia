# enviornment imports
from typing import Literal
import numpy as np
import cppyy
# local imports
from Morelia.Stream.Drain    import DrainToFile
from Morelia.Stream.Collect  import Bucket

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Sree Kondi", "Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class DrainToPVFS(DrainToFile) : 
    """Class to to drain, or save, the data drops collected by a Bucket into an EDF file.

    Attributes:
        file (EdfWriter|None): Text file where streaming data is saved to.
    """
    cppyy.include('/mnt/c/git/Morelia/Code/Morelia/Stream/Drain/Pvfs.h')
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
        print("!!!")
        if( DrainToPVFS.GetExtension(self.fileName) != 
           '.pvfs' ) : 
            raise Exception('[!] DrainToPVFS only accepts \'.pvfs\' ')
        #cppyy.include("Pvfs.h")
        cppyy.load_library('/mnt/c/git/Morelia/Code/Morelia/Stream/Drain/libtest.dll')
        # init
        

    def OpenFile(self) : 
        """Opens and initializes a file using the fileName to save data to. 
        """
        openfile = cppyy.gbl.PVFS_create()
        print("hello")
        
       