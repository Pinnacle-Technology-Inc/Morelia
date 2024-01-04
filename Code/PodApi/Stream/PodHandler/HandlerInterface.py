# enviornment imports
import pandas as pd
import numpy  as np

# local imports
from PodApi.Devices import Pod8206HR, Pod8401HR, Pod8274D
from PodApi.Packets import Packet
from PodApi.Stream.Collect  import Bucket

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class DrainDeviceHandler() : # interface class
    """Interface class for the POD device handlers used by the Drain classes.
    """
    
    @staticmethod
    def GetPodFromBucket(bkt: Bucket) -> Pod8206HR | Pod8401HR | Pod8274D: 
        """Gets the POD device contained in the Bucket.

        Args:
            bkt (Bucket): Bucket to collect streaming data from a POD device.

        Returns:
            Pod8206HR | Pod8401HR: POD device connected to the Bucket.
        """
        return bkt.dataHose.deviceValve.podDevice
    
    @staticmethod
    def _uV(voltage: float|int) -> float :
        """Converts volts to microVolts, rounded to 6 decimal places.

        Args:
            voltage (float | int): number of volts.

        Returns:
            float: voltage in of uV.
        """
        # round to 6 decimal places... add 0.0 to prevent negative zeros when rounding
        return ( round(voltage * 1E6, 12 ) + 0.0 )
    
    # vvvvv      interface methods to implement      vvvvv
    
    def GetDeviceColNamesList(self, includeTime: bool = True) -> list[str] : 
        """Gets a list of all collumn titles.

        Args:
            includeTime (bool, optional): Flag to include 'Time' in the columns list. \
                Defaults to True. 

        Returns:
            list[str]: List of columns.
        """
        pass
    
    def GetDeviceColNamesList(self, includeTime: bool = True) -> list[str] : 
        """Gets a list of all collumn titles.

        Args:
            includeTime (bool, optional): Flag to include 'Time' in the columns list. \
                Defaults to True. 

        Returns:
            list[str]: List of columns.
        """
        pass
    
    def DropToDf(self, timestamps: list[float], data: list[Packet|None]) -> pd.DataFrame : 
        """Converts the timestamps and data into a Pandas DataFrame. The columns should \
            match GetDeviceColNames().

        Args:
            timestamps (list[float]): List of timestamps in seconds for each data packet.
            data (list[Packet | None]): List of streaming binary data packets. 

        Returns:
            pd.DataFrame: DataFrame containing the timestamps and packet data.
        """
        pass
    
    def DropToListOfArrays(self, data: list[Packet | float]) -> list[np.array] : 
        """Unpacks the data Packets into a list of np.arrays formatted to write to an EDF file.

        Args:
            data (list[Packet | float]): List of streaming binary data packets. 

        Returns:
            list[np.array]: List of np.arrays for each Packet part.
        """
        pass
    