# enviornment imports
import pandas as pd

# local imports
from PodApi.Packets import Packet, PacketBinary4
from PodApi.Stream.Drain.PodHandler import DrainDeviceHandler

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"
        
######################################################
        
class Drain8206HR(DrainDeviceHandler) :
    """Class to help handle 8206-HR POD devices for the Drain classes.
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
        if(includeTime) : return ['Time','EEG1','EEG2','EEG3/EMG']
        return ['EEG1','EEG2','EEG3/EMG']
    
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
            'Time' : timestamps,
            'CH0'  : [ self._uV(pkt.Ch(0)) if (isinstance(pkt, PacketBinary4)) else None for pkt in data],
            'CH1'  : [ self._uV(pkt.Ch(1)) if (isinstance(pkt, PacketBinary4)) else None for pkt in data],
            'CH2'  : [ self._uV(pkt.Ch(2)) if (isinstance(pkt, PacketBinary4)) else None for pkt in data]
        })