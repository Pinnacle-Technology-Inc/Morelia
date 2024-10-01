# enviornment imports
from texttable   import Texttable
from io          import IOBase
from threading   import Thread
import time

# local imports
from Setup.SetupOneDevice   import SetupInterface
from Setup.Inputs           import UserInput
from Morelia.Packets        import PacketStandard
from Morelia.Devices        import Pod8480SC
from Morelia.Parameters     import Params8480SC

# authorship
__author__      = "Sree Kondi"
__maintainer__  = "Sree Kondi"
__credits__     = ["Sree Kondi", "Thresa Kelly" "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Setup8480SC(SetupInterface) : 
    """
    Setup_8480SC provides the setup functions for an 8480-SC POD device. 
    
    Attributes:
        _streamMode (bool): Set to True when the user wants to start streaming data from \
            an 8480 POD device, False otherwise.
    """

    # ============ DUNDER METHODS ============      ========================================================================================================================
    
    
    def __init__(self) -> None :
        super().__init__()
        self._podParametersDict : dict[int,Params8480SC] = {} 
        self._streamMode : bool = False


    # ============ PUBLIC METHODS ============      ========================================================================================================================
    
    
    @staticmethod
    def GetDeviceName() -> str : 
        """Returns the name of the POD device.

        Returns:
            str: String of _NAME.
        """
        return('8480-SC')
    

    @staticmethod
    def GetSupportedFileExtensions() -> list[str] : 
        """Returns a list containing valid file extensions. 

        Returns:
            list[str]: List of string file extensions.
        """
        return(['.txt','.csv'])


    def StopStream(self) -> None: 
        """Update the state flag to signal to stop streaming data.
        """
        self._streamMode = False
    
     
    # ============ PRIVATE METHODS ============      ========================================================================================================================
    
    
    # ------------ DEVICE CONNECTION ------------


    def _ConnectPODdevice(self, deviceNum: int, deviceParams: Params8480SC) -> bool :  
        """Creates a POD_8206HR object and write the setup parameters to it. 

        Args:
            deviceNum (int): Integer of the device's number.
            deviceParams (Params_8480SC): Device parameters.

        Returns:
            bool: True if connection was successful, false otherwise.
        """
        success = False 
        # get port name 
        port = deviceParams.port.split(' ')[0] # isolate COM# from rest of string
        
        try : 
            # create POD device 
            pod = Pod8480SC(port=port)
            # test if connection is successful
            if(not self._TestDeviceConnection(pod)): raise Exception('Could not connect to POD device.')
            # write setup parameters
            pod.WriteRead('SET STIMULUS', deviceParams.stimulus)
            pod.WriteRead('SET PREAMP TYPE', deviceParams.preamp)
            pod.WriteRead('SET LED CURRENT', (0, deviceParams.ledCurrent_CH0() ))
            pod.WriteRead('SET LED CURRENT', (1, deviceParams.ledCurrent_CH1() ))
            pod.WriteRead('SET TTL PULLUPS', (deviceParams.ttlPullups ))
            pod.WriteRead('SET ESTIM CURRENT', (0, deviceParams.estimCurrent_CH0() ))
            pod.WriteRead('SET ESTIM CURRENT', (1, deviceParams.estimCurrent_CH1() ))
            pod.WriteRead('SET SYNC CONFIG', (deviceParams.syncConfig ))
            pod.WriteRead('SET TTL SETUP', (deviceParams.ttlSetup ))
            pod.WriteRead('RUN STIMULUS', (0))
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


    def _GetParam_onePODdevice(self, forbiddenNames: list[str] = []) -> Params8480SC : 
        """Asks the user to input all the device parameters. 

        Args:
            forbiddenNames (list[str]): List of port names already used by other devices.

        Returns:
            Params_8480SC: Device parameters.
        """
        # ask for port first
        return(Params8480SC(
            port              =     self._ChoosePort(forbiddenNames),
            stimulus          =    (UserInput.AskForIntInRange('Choose channel (0 or 1) for Stimulus', 0, 1),
                                    *Setup8480SC._ChoosePeriod(),
                                    *Setup8480SC._ChooseWidth(),
                                    UserInput.AskForInt('Enter a value for the stimulus repeat count'),
                                    Setup8480SC._ChooseStimulusConfig()),
            preamp            =     UserInput.AskForIntInRange('\nSet preamp (0-1023)', 0, 1023),
            ledCurrent        =     ( UserInput.AskForIntInRange('\nSet ledCurrent (Hz) for CH0 (0-600)',     0, 600),
                                    UserInput.AskForIntInRange('Set ledCurrent (Hz) for CH1 (0-600)', 0, 600) ),
            ttlPullups        =     UserInput.AskForInt('\nAre the pullups enabled on the TTL lines? (0 for disabled, non-zero for enabled)' ),
            estimCurrent      =     (UserInput.AskForIntInRange('\nSet estimCurrent for Channel0  (0-100)', 0, 100),
                                    UserInput.AskForIntInRange('Set estimCurrent for Channel1  (0-100)', 0, 100)),
            syncConfig        =     Setup8480SC._ChooseSyncConfig(),   
            ttlSetup          =    (UserInput.AskForIntInRange('\nChoose channel (0 or 1) for TTL Setup', 0, 1),
                                    Setup8480SC._TtlSetup(),
                                    UserInput.AskForInt('Enter a debounce value (ms)'))
        ))
        

    @staticmethod
    def _TtlSetup() -> int :
        """Asks the user to input values for Config format values of TTL Setup.

        Returns:
            Formatted TTL Setup config value.
        """
        bit_0 = UserInput.AskForIntInRange("Enter a value (0 for rising edge triggering, 1 for falling edge)", 0, 1)
        bit_1 = UserInput.AskForIntInRange("Enter a value for stimulus triggering (0 for TTL event, 1 for TTL inputs as triggers)", 0, 1 )
        bit_7 = UserInput.AskForIntInRange("Enter a value for TTL Input/Sync (0 for normal TTL operation as input, 1 for TTL pin operate as sync ouput)", 0, 1)
        ttl_value = Pod8480SC.TtlConfigBits(bit_0, bit_1, bit_7)
        return(ttl_value)
        

    @staticmethod
    def _ChooseStimulusConfig() -> int :
        """Asks the user to input values for Config format of Stimulus

        Returns:
            (int): Formatted Stimulus Config value.
        """
        bit_0 = UserInput.AskForIntInRange("Enter a value (0 for Electrical stimulus, 1 for Optical Stimulus)", 0, 1)
        bit_1 = UserInput.AskForIntInRange("Enter a value (0 for Monophasic, 1 for Biphasic)", 0, 1)
        bit_2 = UserInput.AskForIntInRange("Enter a value (0 for standard, 1 for simultaneous)", 0, 1)
        value = Pod8480SC.StimulusConfigBits(bit_0, bit_1, bit_2)
        return(value)


    @staticmethod
    def _ChooseRepeat() -> int :
        """Asks the user to input a value for the number of stimulus pulses to perform.

        Returns:
            int: representing repeat count for command 'SET STIMULUS'.
        """
        return(UserInput.AskForInt("Enter a value for the stimulus repeat count"))
    

    @staticmethod
    def _ChoosePeriod() -> tuple[int] :
        """Asks the user an input value for Stimulus Period, which is then seperated into Period_ms and Period_us. \
           Seperation is required because the 'SET STIMULUS' requires 7 items in payload, and the second and third items \
           is the Period_ms and Period_us.

        Returns: 
            tuple[int]: Formatted period into millisecs and microsecs.  
        """
        user_period = UserInput.AskForFloat(("Enter a simulus period value (ms)")) 
        period = str(user_period).split(".")
        period_ms = int(period[0])
        period_us = int(period[1])
        return(period_ms, period_us) 
    

    @staticmethod
    def _ChooseWidth() -> tuple[int] :
        """Asks the user an input value for Stimulus width, which is then seperated into width_ms and width_us. \
        Seperation is required because the 'SET STIMULUS' requires 7 items in payload, and the fourth and fifth items \
        is the width_ms and width_us. 

        Returns: 
            tuple[int]: Formatted given width into millisecs and microsecs  
        """
        user_width = UserInput.AskForFloat("Enter a stimulus width value (ms)")
        width = str(user_width).split(".")
        width_ms = int(width[0])
        width_us = int(width[1])
        return(width_ms, width_us)
    

    @staticmethod
    def _ChooseSyncConfig() -> int :
        """Asks the user to input values for Sync Config bits.

        Returns: 
            int: Value calculated from the input bits, this value would be given as payload.
        """
        bit_0 = UserInput.AskForIntInRange("Enter a value (0 for LOW sync line, 1 for HIGH sync line)", 0, 1)
        bit_1 = UserInput.AskForIntInRange("Enter a value for Sync Idle (0 to idle the opposite of active state, 1 to sync to idle tristate)", 0, 1) 
        bit_2 = UserInput.AskForIntInRange("Enter a value for Signal/Trigger (0 for sync to show stimulus is in progress, 1 to have sync as input triggers)", 0, 1) 
        final_value = Pod8480SC.SyncConfigBits(bit_0, bit_1, bit_2)
        return(final_value)

        
    def _GetPODdeviceParameterTable(self) -> Texttable :
        """Builds a table containing the parameters for all POD devices.

        Returns:
            Texttable: Texttable containing all parameters.
        """
        # setup table 
        tab = Texttable(160)
        # write column names
        tab.header(['Device #','Port','Stimulus', 'Preamp', 'Led Current', 'TTL Pullups', 'Estim Current', 'Sync Config', 'TTL Setup'])
        # write rows
        for key,val in self._podParametersDict.items() :
            stimulus_str = f" Channel: {val.stimulus[0]}\n Period: {val.stimulus[1]}.{val.stimulus[2]}\n Width: {val.stimulus[3]}.{val.stimulus[4]}\n Repeat: {val.stimulus[5]}\n Config: {val.stimulus[6]}"
            ledCurrent_str = f" Channel 1: {val.ledCurrent[0]}\n Channel 2: {val.ledCurrent[1]}\n "
            estimCurrent_str = f" Channel 1: {val.estimCurrent[0]}\n Channel 2: {val.estimCurrent[1]}\n "
            ttlSetup_str = f" Channel: {val.ttlSetup[0]}\n Config FLag: {val.ttlSetup[1]}\n Debounce: {val.ttlSetup[2]}\n"
            tab.add_row([key, val.port, stimulus_str, val.preamp, ledCurrent_str, val.ttlPullups, estimCurrent_str, val.syncConfig, ttlSetup_str])
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


    def _StreamThreading(self) -> dict[int,Thread] :
        """Opens a save file, then creates a thread for each device to stream and write \
        data from. 

        Returns:
            dict[int,Thread]: Dictionary with keys as the device number and values as the \
                started Thread.
        """
        # set state 
        self._streamMode = True
        # create save files for pod devices
        podFiles = {devNum: self._OpenSaveFile(f"file_{devNum}.txt") for devNum in self._podDevices.keys()}
        # make threads for reading 
        readThreads = {
            # create thread to _StreamUntilStop() to dictionary entry devNum
            devNum : Thread(
                    target = self._StreamUntilStop, 
                    args   = (pod, file))
            # for each device 
            for devNum,pod,file in 
                zip(
                    self._podParametersDict.keys(),     # devNum
                    self._podDevices.values(),          # pod
                    podFiles.values() )                 # file
        }
        for t in readThreads.values() : 
            # start streaming (program will continue until .join() or streaming ends)
            t.start()
        return(readThreads)
        

    def _StreamUntilStop(self, pod: Pod8480SC, file: IOBase) -> None :
        """Saves a log of all packets recieved from the 8480 POD device until the user decides \
        to stop streaming.

        Args:
            pod (POD_8480): POD device to read from. 
            file (IOBase): Opened text file to save data to.
        """
        # initialize
        currentTime : float = 0.0
        t : float = (round(time.time(),9)) # initial time (sec)          
        # start waiting for data   
        while(self._streamMode) : 
            try : 
                # attempt to read packet.         
                read: PacketStandard = pod.ReadPODpacket(timeout_sec=1)
                # update time by adding (dt = tf - ti)
                currentTime += (round(time.time(),9)) - t 
                # build line to write 
                data = [str(currentTime), str(read.CommandNumber())]
                if(read.HasPayload()) : data.append(str(read.Payload()))
                else :                  data.append('None')
                # write to file
                file.write(','.join(data) + '\n')
                # update initial time for next loop 
                t = (round(time.time(),9)) # initial time (sec) 
            except : 
                continue # keep looping 
            # end while 
        # streaming done
        file.close()
