"""Send data to PVFS file."""

__author__      = 'James Hurd'
__maintainer__  = 'Thresa Kelly'
__credits__     = ['Sree Kondi', 'James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2024, Thresa Kelly'
__email__       = 'sales@pinnaclet.com'

from typing import Literal
import numpy as np
import cppyy
import os

from Morelia.Stream.sink import SinkInterface
#from Morelia.Stream.PodHandler import DrainDeviceHandler
from Morelia.Devices import Pod8206HR, Pod8401HR, Pod8274D
from Morelia.packet.data import DataPacket


class PVFSSink(SinkInterface):
    """Stream data to an PVFS file.

    :param file_path: Path to PVFS file to write to.
    :type file_path: str

    :param pod: POD device data is being streamed from.
    :type pod: class:`Pod8206HR | Pod8401HR | Pod8274D`
    """

    def __init__(self, file_path: str, pod: Pod8206HR | Pod8401HR | Pod8274D ) -> None:
        self._file_path = file_path
#        self._dev_handler: DrainDeviceHandler = SinkInterface.get_device_handler(pod)
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
            result = cppyy.gbl.pvfs.PVFS_create(self.file_path)     
            #checking if a PVFS file is created
            if result :
                print("File created successfully") 
                self.DataIndex(result)
        except Exception as e:
            print(f"Error: {e}") 


    
    #make filepath an immutable attribute, changing this could cause problems with
    #data being split across files...
    @property
    def file_path(self) -> str:
        return self._file_path
    
    
    def DataIndex(self, vfs) : 
        """Creates a Data File and an index file. 
        Args:
            dataBucket (Bucket): Bucket to collect streaming data.
            fileName (str): Name (with optional file path) of the file to save data to.
            preampDevice (str | None, optional): Optional preamplifier for the 8401-HR. Defaults to None.
        """
        drain_instance = self._dev_handler
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

    
    async def flush(self, timestamps: list[float], raw_data: list[DataPacket|None]) -> None:
        """Write a drop of data to PVFS.

        :param timestamps: A list of timestamps for data.
        :type timestamps: list[float]
        :param raw_data: A list of data packets from a device.
        :type raw_data: list[:class: Packet|None]
        """
        # print("###")
        #     TODO: have to write data to the created PVFS file.
        #     Get Time Stamps from this function 'GetStartTime' from 
        #     PVFS_IndexedDataFile.cpp. Use PVFS_write from the PVFS.cpp 
        #     to write data to the PVFS file.



        # def CloseFile(self) : 
        #     """Write one drop of data to the save file.
        #     """  
        #     TODO: have to close the PVFS file.
