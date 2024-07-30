# enviornment imports
import pandas as pd
import numpy  as np

# local imports
from Morelia.Devices import Pod8401HR
from Morelia.Packets import Packet, PacketBinary
from Morelia.Stream.PodHandler import DrainDeviceHandler

# authorship
__author__      = "Sree Kondi"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"
        
######################################################

class Drain8274D(DrainDeviceHandler) :
    """Class to help handle 8274D POD devices for the Drain classes.
    """
    
    def GetDeviceColNames(self) -> str :
        """Gets a string of the column names formatter for a text file.

        Returns:
            str: String of the filenames separated by commas and ending in a newline.
        """
        return ','.join(self.GetDeviceColNamesList()) + '\n'
    
    def GetDeviceColNamesList(self, includeTime: bool = True) -> list[str] : 
        """Gets a list of all collumn titles.

        Args:
            includeTime (bool, optional): Flag to include 'Time' in the columns list. \
                Defaults to True. 

        Returns:
            list[str]: List of columns.
        """
        if(includeTime) : return ['Time', 'LengthBytes', 'Data']
        return ['Length','Data']
        
    
    def DropToDf(self, timestamps: list[float], data: list[Packet | None]) -> pd.DataFrame : 
        """Converts the timestamps and data into a Pandas DataFrame. The columns should \
        match GetDeviceColNames().

        Args:
            timestamps (list[float]): List of timestamps in seconds for each data packet.
            data (list[Packet | None]): List of streaming binary data packets. 

        Returns:
            pd.DataFrame: DataFrame containing the timestamps and packet data.
        """
        return pd.DataFrame({
            'Time'          : timestamps,
            'LengthBytes'   : [ pt.binaryLength if (isinstance(pt, PacketBinary)) else pt for pt in data],
            'Data'          : [ pt.binaryData if (isinstance(pt, PacketBinary)) else pt for pt in data]
        })
        
    def DropToListOfArrays(self, data: list[Packet|float]) -> list[np.array] : 
        """Unpacks the data Packets into a list of np.arrays formatted to write to an EDF file.

        Args:
            data (list[Packet | float]): List of streaming binary data packets. 

        Returns:
            list[np.array]: List of np.arrays for each Packet part.
        """
        # unpack binary Packet
        dlist_list : list[list[float]] = [
            [ (pt.binaryLength) if (isinstance(pt, PacketBinary)) else pt for pt in data],
            [ (pt.binaryData) if (isinstance(pt, PacketBinary)) else pt for pt in data]
        ]
        # convert to np arrays
        dlist_arr = []
        for l in dlist_list : 
            dlist_arr.append( np.array(l) )
        # finish
        return dlist_arr
        