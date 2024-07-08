# enviornment imports
from typing import Literal
import numpy as np

import os

# importing cppyy
import cppyy
from cppyy import gbl
# local imports
from Morelia.Stream.Drain    import DrainToFile
from Morelia.Stream.Collect  import Bucket
from Morelia.Stream.PodHandler.Handle8206HR        import Drain8206HR

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Sree Kondi", "Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class DrainToPVFS(DrainToFile) : 
    """Class to to drain, or save, the data drops collected by a Bucket into an PVFS file.

    Attributes:
        file (EdfWriter|None): Text file where streaming data is saved to.
    """
    def __init__(self, dataBucket: Bucket, fileName: str, preampDevice: str|None = None) -> None:
        """Set class instance variables.

        Args:
            dataBucket (Bucket): Bucket to collect streaming data.
            fileName (str): Name (with optional file path) of the file to save data to.
            preampDevice (str | None, optional): Optional preamplifier for the 8401-HR. Defaults to None.

        Raises:
            Exception: DrainToPVFS only accepts '.pvfs' extensions.
        """
        super().__init__(dataBucket, fileName, preampDevice)
        # check for valid file extension 
        if( DrainToPVFS.GetExtension(self.fileName) != '.pvfs' ) : 
            raise Exception('[!] DrainToPVFS only accepts \'.pvfs\' ')
        
    def DataIndex(self, vfs) : 
        """Creates a Data File and an index file. 
        Args:
            dataBucket (Bucket): Bucket to collect streaming data.
            fileName (str): Name (with optional file path) of the file to save data to.
            preampDevice (str | None, optional): Optional preamplifier for the 8401-HR. Defaults to None.
        """
        drain_instance = Drain8206HR()
        # Getting Channel Names
        base_names = drain_instance.GetDeviceColNamesList()
        for each in base_names :
            # adding data extension (.idat) to each column name
            sub_data_filename = each + cppyy.gbl.pvfs.PVFS_DATA_EXTENSION
            # adding index extension (.index) to each column name
            sub_index_filename = each + cppyy.gbl.pvfs.PVFS_INDEX_EXTENSION
            print("data : " + sub_data_filename)
            # creating a data file with the filename above
            data_file = cppyy.gbl.pvfs.PVFS_fcreate(vfs, sub_data_filename)
            print("index : " + sub_index_filename)
             # creating a index file with the filename above
            index_file = cppyy.gbl.pvfs.PVFS_fcreate(vfs, sub_index_filename)
            #checking if data file has been created successfully.
            if data_file:
                print("PVFS_fcreate data  passed")
                # Create an index header object
                header = cppyy.gbl.pvfs.PvfsIndexHeader()
                if cppyy.gbl.pvfs.PVFS_write_index_file_header(data_file, header) == cppyy.gbl.pvfs.PVFS_OK:
                    header = cppyy.gbl.pvfs.PVFS_OK
                    print("write header test passed", header)
                else:
                    print("write header test failed")


    def OpenFile(self) : 
        """Opens and initializes a file using the fileName to save data to. 
        """
        try:
            #include a path to wherever the Pvfs.h is located, make sure you put '/mnt/c' if using wsl
            #first, make sure you include Pvfs.h file into your cppyy.

            path = os.path.dirname(os.path.abspath(__file__))
            pvfs_h_path = os.path.join(path, 'Pvfs.h')
            cppyy.include(pvfs_h_path)  

            #second, make sure you include your library (.dll file) into your cppyy.
            # You can get this .dll file by compiling the Pvfs.cpp file.
            libtest_h_path = os.path.join(path, 'libtest.dll')
            cppyy.load_library(libtest_h_path)
            print("\nPvfs library loaded successfully!") 
            
            #creating an empty PVFS file
            # Call the PVFS_create function from Pvfs.cpp 
            result = cppyy.gbl.pvfs.PVFS_create(self.fileName)     
            #checking if a PVFS file is created
            if result :
                print("File created successfully") 
                self.DataIndex(result)
        except Exception as e:
            print(f"Error: {e}") 
             

    # def DrainDropToFile(self) : 
    #     """Write one drop of data to the save file.
    #     """  
    #     TODO: have to write data to the created PVFS file.
    #     Get Time Stamps from this function 'GetStartTime' from 
    #     PVFS_IndexedDataFile.cpp. Use PVFS_write from the PVFS.cpp 
    #     to write data to the PVFS file.



    # def CloseFile(self) : 
    #     """Write one drop of data to the save file.
    #     """  
    #     TODO: have to close the PVFS file.

    
