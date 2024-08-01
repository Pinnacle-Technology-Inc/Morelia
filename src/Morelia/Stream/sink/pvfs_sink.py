"""Send data to PVFS file."""

__author__      = 'Sree Kondi'
__maintainer__  = 'Thresa Kelly'
__credits__     = ['Sree Kondi', 'James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2024, Thresa Kelly'
__email__       = 'sales@pinnaclet.com'

from typing import Literal
import numpy as np
import cppyy
import os
import ctypes 
import zlib 
from threading import Thread, Lock

from Morelia.Stream.sink import SinkInterface
from Morelia.Stream.PodHandler import DrainDeviceHandler
from Morelia.Devices import Pod8206HR, Pod8401HR, Pod8274D
from Morelia.Packets import Packet


class PVFSSink(SinkInterface):
    """Stream data to an PVFS file.

    :param file_path: Path to PVFS file to write to.
    :type file_path: str

    :param pod: POD device data is being streamed from.
    :type pod: class:`Pod8206HR | Pod8401HR | Pod8274D`
    """
    def __init__(self, file_path: str, pod: Pod8206HR | Pod8401HR | Pod8274D ) -> None:
        self._file_path = file_path
        self._dev_handler: DrainDeviceHandler = SinkInterface.get_device_handler(pod)


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
        
        # initialize the member variables
        self.m_DataFileIndex = 0
        self.m_DataChunkCRC = 0  # Or appropriate initialization
        self.m_DataFileWriteCache = None  # Set this to the actual initial value or object
        self.m_IndexFileWriteCache = None  # Set this to the actual initial value or object
        self.m_Modified = False
        # self.seconds = 0
        # self.subseconds = 0.0
        
        


    
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

        print("\nTest PVFS_get_channel_list")
        names = cppyy.gbl.std.vector('std::string')()
        retval = int
        vfs = cppyy.gbl.pvfs.PVFS_open(self._file_path)
        if vfs:
            # Retrieve the channel list
            retval = cppyy.gbl.pvfs.PVFS_get_channel_list(vfs, names)
            if retval == cppyy.gbl.pvfs.PVFS_OK:
                # Print each channel name
                for name in names:
                    print(name)
                print("PVFS_get_channel_list test passed")
            else:
                print("PVFS_get_channel_list error during read")

    
    def WriteCacheToFile(file):
        if mutex.Lock():
            result = DoWriteCacheToFile(file)
        mutex.unlock()
        return result

           
    def write_data(self,data: bytes,length: int, do_crc: bool = False):
        self.m_DataFileIndex += length

        # Calculate CRC if requested
        if do_crc:
            cppyy.gbl.CRC32.AppendBytes(data, length)

        # Write data to file cache
        if cppyy.gbl.Write(data, length, self.m_DataFileWriteCache):
            # Flush index file if data file filled up
            self.WriteCacheToFile()

        # Set modified flag
        self.m_Modified = True
        # so that is the template
        return 0  # Return value as in C++

    
    async def flush(self, timestamps: list[float], raw_data: list[Packet|None]) -> None:
        """Write a drop of data to PVFS.

        :param timestamps: A list of timestamps for data.
        :type timestamps: list[float]
        :param raw_data: A list of data packets from a device.
        :type raw_data: list[:class: Packet|None]
        """         
        reservedSpace	= 0
        seconds			= 0
        subseconds		= 0.0

        try:
            # Convert raw data to DataFrame
            structured_data: pd.DataFrame = self._dev_handler.DropToDf(timestamps, raw_data)
            
            print("!!!", structured_data)
        
            if (self.m_DataFileIndex > 0) :
                self.data_chunk_crc = cppyy.gbl.CRC32.GetCRC()
                await self.write_data(self.data_chunk_crc)
        #         # Close the data file      
        #         cppyy.gbl.pvfs.PVFS_fclose(data_file)

        

        #     # Close the PVFS file
        #     cppyy.gbl.pvfs.PVFS_close((vfs))

        except Exception as e:
            print(f"Error during flush: {e}") 

