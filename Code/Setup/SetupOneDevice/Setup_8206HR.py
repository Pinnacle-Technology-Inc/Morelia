# enviornment imports
from   texttable    import Texttable
from   threading    import Thread

# local imports
from Setup.SetupOneDevice   import SetupInterface
from Setup.Inputs           import UserInput
from Morelia.Devices        import Pod8206HR
from Morelia.Parameters     import Params8206HR
from Morelia.Stream.Collect import Bucket, DrainBucket

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Setup8206HR(SetupInterface) : 
    """
    Setup_8206HR provides the setup functions for an 8206-HR POD device.
    
    Attributes:
        _bucketAccess (dict[int,Bucket]): Dictionary with device number keys and Bucket values. \
            This is updated in _StreamThreading() and cleared in StopStream().
    """

    # ============ GLOBAL CONSTANTS ============      ========================================================================================================================


    _PHYSICAL_BOUND_uV : int = 2046 # max/-min stream value in uV
    """Class-level integer representing the max/-min physical value in uV. \
    Used for EDF files. 
    """

    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self) -> None:
        super().__init__()
        self._podParametersDict : dict[int,Params8206HR] = {}   
        self._bucketAccess : dict[int,Bucket] = {}


    # ============ PUBLIC METHODS ============      ========================================================================================================================


    @staticmethod
    def GetDeviceName() -> str : 
        """Returns the name of the 8206-HR POD device.

        Returns:
            str: 8206-HR.
        """
        return('8206-HR')
    

    # ============ PRIVATE METHODS ============      ========================================================================================================================


    # ------------ DEVICE CONNECTION ------------


    def _ConnectPODdevice(self, deviceNum: int, deviceParams: Params8206HR) -> bool : 
        """Creates a POD_8206HR object and write the setup parameters to it. 

        Args:
            deviceNum (int): Integer of the device's number.
            deviceParams (Params_8206HR): Device's parameters.

        Returns:
            bool: True if connection was successful, false otherwise.
        """
        success = False 
        try : 
            # get port name 
            port = deviceParams.port.split(' ')[0] # isolate COM# from rest of string
            # create POD device 
            pod = Pod8206HR(port=port, preampGain=deviceParams.preamplifierGain)
            # test if connection is successful
            if(not self._TestDeviceConnection(pod)) : raise Exception('Could not connect to POD device.')
            # write setup parameters
            pod.WriteRead('SET SAMPLE RATE', deviceParams.sampleRate )
            pod.WriteRead('SET LOWPASS', (0, deviceParams.EEG1()    ))
            pod.WriteRead('SET LOWPASS', (1, deviceParams.EEG2()    ))
            pod.WriteRead('SET LOWPASS', (2, deviceParams.EEG3_EMG()))
            # successful write if no exceptions raised 
            self._podDevices[deviceNum] = pod
            success = True
            print('Successfully connected device #'+str(deviceNum)+' to '+port+'.')
        except Exception as e :
            self._podDevices[deviceNum] = False # fill entry with bad value
            print('[!] Failed to connect device #'+str(deviceNum)+' to '+port+': '+str(e))
        # return True when connection successful, false otherwise
        return(success)


    # ------------ SETUP POD PARAMETERS ------------
    

    def _GetParam_onePODdevice(self, forbiddenNames: list[str] = []) -> Params8206HR : 
        """Asks the user to input all the device parameters. 

        Args:
            forbiddenNames (list[str]): List of port names already used by other devices.

        Returns:
            dict[str,(str|int|dict[str,int])]: Dictionary of device parameters.
        """
        return(Params8206HR(
            port             =   self._ChoosePort(forbiddenNames),
            sampleRate       =   UserInput.AskForIntInRange('Set sample rate (Hz)', 100, 2000),
            preamplifierGain =   self._ChoosePreampGain(),
            lowPass          = ( UserInput.AskForIntInRange('Set lowpass (Hz) for EEG1',     11, 500),
                                 UserInput.AskForIntInRange('Set lowpass (Hz) for EEG2',     11, 500),
                                 UserInput.AskForIntInRange('Set lowpass (Hz) for EEG3/EMG', 11, 500) )
        ))
    
    @staticmethod
    def _ChoosePreampGain() -> int :
        """Asks user for the preamplifier gain of their POD device.

        Returns:
            int: Integer 10 or 100 for the preamplifier gain.
        """
        gain = UserInput.AskForInt('Set preamplifier gain')
        # check for valid input 
        if(gain != 10 and gain != 100):
            # prompt again 
            print('[!] Input must be 10 or 100.')
            return(Setup8206HR._ChoosePreampGain())
        # return preamplifier gain 
        return(gain)    
    
    
    # ------------ DISPLAY POD PARAMETERS ------------


    def _GetPODdeviceParameterTable(self) -> Texttable :
        """Builds a table containing the parameters for all POD devices.

        Returns:
            Texttable: Texttable containing all parameters.
        """
        # setup table 
        tab = Texttable(110)
        # write column names
        tab.header(['Device #','Port','Sample Rate (Hz)', 'Preamplifier Gain', 'EEG1 Low-pass (Hz)','EEG2 Low-pass (Hz)','EEG3/EMG Low-pass (Hz)'])
        # write rows
        for key,val in self._podParametersDict.items() :
            tab.add_row([key, val.port, val.sampleRate, val.preamplifierGain, val.EEG1(), val.EEG2(), val.EEG3_EMG()])       
        return(tab)
    

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
