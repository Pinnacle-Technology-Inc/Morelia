# enviornment imports
from texttable   import Texttable
from io          import IOBase
from threading   import Thread
import time

# local imports
from Setup.SetupOneDevice   import SetupInterface
from Setup.Inputs           import UserInput
from Morelia.Devices        import Pod8274D
from Morelia.Parameters     import Params8274D
from Morelia.Stream.Collect import Bucket, DrainBucket

# authorship
__author__      = "Sree Kondi"
__maintainer__  = "Sree Kondi"
__credits__     = ["Sree Kondi", "Thresa Kelly" "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Setup8274D(SetupInterface) : 
    """
    Setup_8480SC provides the setup functions for an 8480-SC POD device. 
    
    Attributes:
        _streamMode (bool): Set to True when the user wants to start streaming data from \
            an 8480 POD device, False otherwise.
    """

    # ============ DUNDER METHODS ============      ========================================================================================================================
    
    
    def __init__(self) -> None :
        super().__init__()
        self._podParametersDict : dict[int,Params8274D] = {} 
        self._streamMode : bool = False


    # ============ PUBLIC METHODS ============      ========================================================================================================================
    
    
    @staticmethod
    def GetDeviceName() -> str : 
        """Returns the name of the POD device.

        Returns:
            str: String of _NAME.
        """
        return('8274D')
    

    @staticmethod
    def GetSupportedFileExtensions() -> list[str] : 
        """Returns a list containing valid file extensions. 

        Returns:
            list[str]: List of string file extensions.
        """
        return(['.txt','.csv', '.edf'])
    
    @staticmethod
    def NameDecode(name: str) -> str:
        """Converts decimal valued name into more understandable ascii values. 

        Args:
            name (str): This represents the name of the device(which is in decimal value.)
        
        Returns:
            str: returns name of the device in ascii values. 
        """
        decoded_name = ""
        for each in name :
            decoded_name += chr(int(each))
        return decoded_name
    
    def StopStream(self) -> None: 
        """Update the state flag to signal to stop streaming data.
        """
        self._streamMode = False
     
    # ============ PRIVATE METHODS ============      ========================================================================================================================
    
    
    # ------------ DEVICE CONNECTION ------------


    def _ConnectPODdevice(self, deviceNum: int, deviceParams: Params8274D) -> bool :  
        """Creates a POD_8274D object and write the setup parameters to it. 

        Args:
            deviceNum (int): Integer of the device's number.
            deviceParams (Params_8274D): Device parameters.

        Returns:
            bool: True if connection was successful, false otherwise.
        """
        success = False 
        # get port name 
        port = deviceParams.port.split(' ')[0] # isolate COM# from rest of string
        
        try : 
            # create POD device 
            pod = Pod8274D(port=port)
            # test if connection is successful
            if(not self._TestDeviceConnection(pod)): raise Exception('Could not connect to POD device.')
            # write setup parameters
            address = pod.WriteRead('LOCAL SCAN', deviceParams.localScan)
            addres_to_connect = address['Payload'][1:7]
            time.sleep(5)
            pod.WriteRead('CONNECT BY ADDRESS', (addres_to_connect)) 
            time.sleep(1)
            pod.WriteRead('SET SAMPLE RATE', deviceParams.sampleRate)
            time.sleep(1)
            pod.WriteRead('SET PERIOD', deviceParams.period)
            time.sleep(1)
            name = pod.WriteRead('GET NAME') 
            # successful write if no exceptions raised 
            self._podDevices[deviceNum] = pod
            success = True
            print('Successfully connected '+ Setup8274D.NameDecode(name)+ ' device #' +str(deviceNum)+' to '+port+'.')
        except Exception as e :
            self._podDevices[deviceNum] = False # fill entry with bad value
            print('[!] Failed to connect device #'+str(deviceNum)+' to '+port+': '+str(e))
        # return True when connection successful, false otherwise 
        return(success)
    

    def _GetParam_onePODdevice(self, forbiddenNames: list[str] = []) -> Params8274D : 
        """Asks the user to input all the device parameters. 

        Args:
            forbiddenNames (list[str]): List of port names already used by other devices.

        Returns:
            Params_8480SC: Device parameters.
        """
        # ask for port first
        return(Params8274D(
            port              =     self._ChoosePort(forbiddenNames), 
            localScan         =     UserInput.AskForIntInRange('\nSet Local Scan (1 enables, 0 disables)', 0, 1),
            sampleRate        =     UserInput.AskForIntInList('\nSet Sample Rate (0 for 1024, 1 for 512, 2 for 256, 3 for 128)', [0,1,2,3]),
            period            =     UserInput.AskForInt('\nSet Period (greater than or equal to 0)'),
        ))
        
    def _GetPODdeviceParameterTable(self) -> Texttable :
        """Builds a table containing the parameters for all POD devices.

        Returns:
            Texttable: Texttable containing all parameters.
        """
        # setup table 
        tab = Texttable(160)
        # write column names
        tab.header(['Device #','Port','Local Scan', 'Period', 'Sample Rate'])
        # write rows
        for key,val in self._podParametersDict.items() :
            tab.add_row([ key, 
                          val.port, 
                          f" Local Scan: {val.localScan}\n  ", 
                          f" Period: {val.period}\n  ", 
                          f" Sample Rate: {val.sampleRate}"])
        return(tab)
    

    def _OpenSaveFile_EDF(self, fname: str, devNum: int) :
        """EDF files are not supported for 8480 POD devices. Overwrites the \
        parent's method, which would open an EDF file and write the header.

        Args:
            fname (str): String filename. Not used.
            devNum (int): Integer device number. Not used.

        Raises:
            Exception: EDF filetype is not supported for 8480 POD devices.
        """
        raise Exception('[!] POD Device 8480-SC does not support EDF filetype.')
    

    def _OpenSaveFile_TXT(self, fname: str) -> IOBase : 
        """Opens a text file and writes the column names. Writes the current date/time \
            at the top of the txt file.

        Args:
            fname (str): String filename. 

        Returns:
            IOBase: Opened file.
        """
        # open file and write column names 
        f = open(fname, 'w')
        # write time
        f.write( self._GetTimeHeader_forTXT() ) 
        # columns names
        f.write('\nTime (s),Command Number,Payload\n')
        return(f)


# ------------ STREAM ------------


    def _StreamThreading(self) -> tuple[dict[int,Thread]] :
        """Start streaming from each POD device and save each to a file.

        Returns:
            tuple[dict[int,Thread]]: Tuple of two items, the first is for the bucket and the second is the drain. \
                Each item is a dictionary with device number keys and started Thread items.
        """
        # create objects to collect and save streaming data 
        allBuckets : dict[int,Bucket]       = { devNum : Bucket(pod) for devNum,pod in self._podDevices.items() }
        allDrains  : dict[int,DrainBucket]  = { devNum : DrainBucket(bkt, self._BuildFileName(devNum)) for devNum,bkt in allBuckets.items() }
        # start collecting data and saving to file 
        bucketThreads : dict[int,Thread] = { devNum : bkt.StartCollecting()   for devNum, bkt in allBuckets.items() } # thread started inside StartCollecting
        drainThreads  : dict[int,Thread] = { devNum : drn.DrainBucketToFile() for devNum, drn in allDrains.items()  } # thread started inside DrainBucketToFile
        # set class variable 
        self._bucketAccess = allBuckets
        # return started threads
        return ( bucketThreads, drainThreads )
        
        
    def StopStream(self) -> None :
        """Write a command to stop streaming data to all POD devices."""
        # signal for each bucket to stop collecting data, which writes command to stop streaming to the POD device
        for bkt in self._bucketAccess.values() : 
            bkt.StopCollecting()
        # clear class variable
        self._bucketAccess = {}
