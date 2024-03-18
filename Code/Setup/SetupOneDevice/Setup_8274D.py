# enviornment imports
from texttable   import Texttable
from io          import IOBase
from threading   import Thread
import time

# local imports
from Setup.SetupOneDevice   import SetupInterface
from Setup.Inputs           import UserInput
from PodApi.Devices         import Pod8274D
from PodApi.Parameters      import Params8274D
from PodApi.Stream.Collect  import Bucket, DrainBucket

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
        return(['.txt','.csv'])
        # NOTE TK --
        # why no EDF? Is there a reason?


    def StopStream(self) -> None: 
        """Update the state flag to signal to stop streaming data.
        """
        self._streamMode = False
    
     
    # ============ PRIVATE METHODS ============      ========================================================================================================================
    
    # NOTE TK -- 
    # We want to keep all function names formatted in capital camel case.
    # So this should be DecToAscii
    # NOTE TK -- 
    # is this a static method? If so be sure to use @staticmethod decorator. 
    # If you don't, 'name' may be interpreted as a 'self'.
    # NOTE TK --
    # Also be sure to use a an annotation for the function argument and return
    # Such as the following
    #   @staticmethod
    #   def DecToAscii(name: str) -> str:    
    # # NOTE TK -- 
    # Can you add more detail to the docstring description? I dont really know
    # what this function is for. 
    # NOTE TK -- 
    # Returns: in the docstring are not correctly formatted. Strings should be 
    # 'str' and you need to add 'str: type description here'.
    # NOTE TK -- 
    # docstring needs an 'Args: ' component. 
    
    def dec_to_asci(name) : 
        """Returns the corresponding ascii values. 

        Returns:
            string 
        """
        print("Device name: ")
        for each in name :
            print(chr(each), end='')
    
    # ------------ DEVICE CONNECTION ------------


    def _ConnectPODdevice(self, deviceNum: int, deviceParams: Params8274D) -> bool :  
        """Creates a POD_8206HR object and write the setup parameters to it. 

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
            pod.WriteRead('CONNECT BY ADDRESS', (address))
            name = pod.WriteRead('GET NAME') 
            print(Setup8274D.dec_to_asci(name)) # NOTE TK -- why are you printing here? is this for debug?
            pod.WriteRead('SET PERIOD', deviceParams.period) 
            # successful write if no exceptions raised 
            self._podDevices[deviceNum] = pod
            success = True
            print('Successfully connected device #'+str(deviceNum)+' to '+port+'.')
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
            
            # NOTE TK -- 
            # What does Local Scan (0 or 1) mean? It would be better to be more descriptive when asking 
            # for user input. Such as the following:
            #       UserInput.AskYN(question="Enable Local Scan")
            localScan         =     UserInput.AskForIntInRange('\nSet Local Scan (0 or 1)', 0, 1),
            
            # NOTE TK -- 
            # Similar problem here. What does Sample Rate (0,1,2,3) mean? I can see that it is 
            # 0 = 1024, 1 = 512, 2 = 256, 3 = 128 in the spreadsheet, but the user should not 
            # have to look at the spreadsheet to use this code. 
            # So make this user input request more clear
            sampleRate        =     UserInput.AskForIntInList('\nSet Sample Rate (0,1,2,3)', [0,1,2,3]),
            
            # NOTE TK -- 
            # The 'AskForInput' function is too general for this, as the user can respond with any 
            # string. This is very error prone. Period needs to be a number. Use AskForIntInRange
            # or AskForFloatInRange instead. For example, you can set the minimum range as zero 
            # to prevent negative numbers 
            period            =     UserInput.AskForInput('\nSet Period '),
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
            # NOTE TK --
            # This is a pretty minor comment here. But you could be more efficient by doing this all in 
            # one line. This a little memory on the computer I think. But no problem your way though!
            # tab.add_row([ key, 
            #               val.port, 
            #               f" Local Scan: {val.localScan}\n  ", 
            #               f" Period: {val.period}\n  ", 
            #               f" Sample Rate: {val.sampleRate}"])
            localScan_str = f" Local Scan: {val.localScan}\n  "
            period_str = f" Period: {val.period}\n  "
            samplerate_str = f" Sample Rate: {val.sampleRate}"
            tab.add_row([key, val.port, localScan_str, period_str, samplerate_str])
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
