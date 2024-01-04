# enviornment imports
import pandas as pd
import numpy  as np

# local imports
from PodApi.Devices import Pod8401HR
from PodApi.Packets import Packet, PacketBinary4
from PodApi.Stream.PodHandler import DrainDeviceHandler

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
        if(includeTime) : return ['Time','Length','Data']
        return ['Length','Data']
        