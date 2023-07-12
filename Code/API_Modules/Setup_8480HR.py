# enviornment imports
from texttable   import Texttable
from io          import IOBase
from threading   import Thread
import time

# local imports
from Setup_PodInterface  import Setup_Interface
from PodDevice_8480HR    import POD_8480HR
from GetUserInput        import UserInput
from Setup_PodParameters import Params_8480HR

# authorship
__author__      = "Sree Kondi"
__maintainer__  = "Sree Kondi"
__credits__     = ["Sree Kondi", "Thresa Kelly" "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Sree Kondi"
__email__       = "sales@pinnaclet.com"


class Setup_8480HR(Setup_Interface) : 
    """
    Setup_8480HR provides the setup functions for an 8480-HR POD device. 
    
    Attributes:
        _streamMode (bool): Set to True when the user wants to start streaming data from \
            an 8480 POD device, False otherwise.
    """

    # ============ GLOBAL CONSTANTS ============      ========================================================================================================================


    _NAME : str = '8480-HR' # overwrite from parent
    """Class-level string containing the POD device name.
    """


    # ============ DUNDER METHODS ============      ========================================================================================================================
    
    
    def __init__(self) -> None:
        super().__init__()
        self._podParametersDict : dict[int,Params_8480HR] = {} 
        self._streamMode : bool = False


    # ============ PUBLIC METHODS ============      ========================================================================================================================
    
    
    @staticmethod
    def GetDeviceName() -> str : 
        """Returns the name of the POD device.

        Returns:
            str: String of _NAME.
        """
        return(Setup_8480HR._NAME)
    

    @staticmethod
    def GetSupportedFileExtensions() -> list[str] : 
        """Returns a list containing valid file extensions. 

        Returns:
            list[str]: List of string file extensions.
        """
        return(['.txt'])


    def StopStream(self) -> None: 
        """Update the state flag to signal to stop streaming data.
        """
        self._streamMode = False
    
     
    # ============ PRIVATE METHODS ============      ========================================================================================================================
    
    
    # ------------ DEVICE CONNECTION ------------


    """Creates a POD_8206HR object and write the setup parameters to it. 

        Args:
            deviceNum (int): Integer of the device's number.
            deviceParams (Params_8480HR): Device parameters.

        Returns:
            bool: returns true if failed, false otherwise.
    """
    def _ConnectPODdevice(self, deviceNum: int, deviceParams: Params_8480HR) -> bool :  
            # get port name 
            port = deviceParams.port.split(' ')[0] # isolate COM# from rest of string
            # create POD device 
            self._podDevices[deviceNum] = POD_8480HR(port=port)
            # test if connection is successful
            failed = True
            if(self._TestDeviceConnection(self._podDevices[deviceNum])):
            #write setup parameters
                self._podDevices[deviceNum].WriteRead('SET STIMULUS', deviceParams.stimulus)
                self._podDevices[deviceNum].WriteRead('SET PREAMP TYPE', deviceParams.preamp)
                self._podDevices[deviceNum].WriteRead('SET LED CURRENT', (0, deviceParams.ledCurrent_CH0() ))
                self._podDevices[deviceNum].WriteRead('SET LED CURRENT', (1, deviceParams.ledCurrent_CH1() ))
                self._podDevices[deviceNum].WriteRead('SET TTL PULLUPS', (deviceParams.ttlPullups ))
                self._podDevices[deviceNum].WriteRead('SET ESTIM CURRENT', (0, deviceParams.estimCurrent_CH0() ))
                self._podDevices[deviceNum].WriteRead('SET ESTIM CURRENT', (1, deviceParams.estimCurrent_CH1() ))
                self._podDevices[deviceNum].WriteRead('SET SYNC CONFIG', (deviceParams.syncConfig ))
                self._podDevices[deviceNum].WriteRead('SET TTL SETUP', (deviceParams.ttlSetup ))
                self._podDevices[deviceNum].WriteRead('RUN STIMULUS', (0))
            failed = False
            # check if connection failed 
            if(failed) :
                print('[!] Failed to connect POD device #'+str(deviceNum)+' to '+port+'.')
            else :
                print('Successfully connected POD device #'+str(deviceNum)+' to '+port+'.')
            # return True when connection successful, false otherwise
                return(not failed)


    # ------------ SETUP POD PARAMETERS ------------


    def _GetParam_onePODdevice(self, forbiddenNames: list[str] = []) -> Params_8480HR : 
        """Asks the user to input all the device parameters. 

        Args:
            forbiddenNames (list[str]): List of port names already used by other devices.

        Returns:
            Params_8480HR: Device parameters.
        """
        # ask for port first
        return(Params_8480HR(
            port              =     self._ChoosePort(forbiddenNames),
            stimulus          =    (UserInput.AskForIntInRange('Choose channel (0 or 1) for Stimulus', 0, 1),
                                    *Setup_8480HR._ChoosePeriod(),
                                    *Setup_8480HR._ChooseWidth(),
                                    UserInput.AskForInt('Enter a value for the stimulus repeat count'),
                                    Setup_8480HR._ChooseStimulusConfig()),
            preamp            =     UserInput.AskForIntInRange('\nSet preamp (0-1023)', 0, 1023),
            ledCurrent        =     ( UserInput.AskForIntInRange('\nSet ledCurrent (Hz) for CH0 (0-600)',     0, 600),
                                    UserInput.AskForIntInRange('Set ledCurrent (Hz) for CH1 (0-600)', 0, 600) ),
            ttlPullups        =     UserInput.AskForInt('\nAre the pullups enabled on the TTL lines? (0 for disabled, non-zero for enabled)' ),
            estimCurrent      =     (UserInput.AskForIntInRange('\nSet estimCurrent for Channel0  (0-100)', 0, 100),
                                    UserInput.AskForIntInRange('Set estimCurrent for Channel1  (0-100)', 0, 100)),
            syncConfig        =     Setup_8480HR._ChooseSyncConfig(),   
            ttlSetup          =    (UserInput.AskForIntInRange('\nChoose channel (0 or 1) for TTL Setup', 0, 1),
                                    Setup_8480HR._TtlSetup(),
                                    UserInput.AskForInt('Enter a debounce value (ms)'))
        ))
        

    @staticmethod
    def _TtlSetup() -> int:
        """Asks the user to input values for Config format values of TTL Setup.

        Returns:
            Formatted TTL Setup config value.
        """
        bit_0 = UserInput.AskForIntInRange("Enter a value (0 for rising edge triggering, 1 for falling edge)", 0, 1)
        bit_1 = UserInput.AskForIntInRange("Enter a value for stimulus triggering (0 for TTL event, 1 for TTL inputs as triggers)", 0, 1 ) # NOTE : what do 0 or 1 mean here? 
        bit_7 = UserInput.AskForIntInRange("Enter a value for TTL Input/Sync (0 for normal TTL operation as input, 1 for TTL pin operate as sync ouput)", 0, 1) # NOTE : what do 0 or 1 mean here? 
        ttl_value = POD_8480HR.TtlConfigBits(bit_0, bit_1, bit_7)
        return(ttl_value)
        

    @staticmethod
    def _ChooseStimulusConfig() -> int :
        """Asks the user to input values for Config format of Stimulus

        Returns:
            Formatted Stimulus Config value.
        """
        bit_0 = UserInput.AskForIntInRange("Enter a value (0 for Electrical stimulus, 1 for Optical Stimulus)", 0, 1)
        bit_1 = UserInput.AskForIntInRange("Enter a value (0 for Monophasic, 1 for Biphasic)", 0, 1)
        bit_2 = UserInput.AskForIntInRange("Enter a value (0 for standard, 1 for simultaneous)", 0, 1)
        value = POD_8480HR.StimulusConfigBits(bit_0, bit_1, bit_2)
        return(value)


    @staticmethod
    def _ChooseRepeat() -> int:
        """Asks the user to input a value for the number of stimulus pulses to perform.

        Returns:
            (int): representing repeat count for command 'SET STIMULUS'.
        """
        return(UserInput.AskForInt("Enter a value for the stimulus repeat count"))
    

    @staticmethod
    def _ChoosePeriod():
        """Asks the user an input value for Stimulus Period, which is then seperated into Period_ms and Period_us. \
           Seperation is required because the 'SET STIMULUS' requires 7 items in payload, and the second and third items \
           is the Period_ms and Period_us.

        Returns: 
            Formatted period into millisecs and microsecs.  
        """
        user_period = UserInput.AskForFloat(("Enter a simulus period value (ms)")) 
        period = str(user_period).split(".")
        period_ms = int(period[0])
        period_us = int(period[1])
        return(period_ms, period_us) 
    

    @staticmethod
    def _ChooseWidth():
        """Asks the user an input value for Stimulus width, which is then seperated into width_ms and width_us. \
        Seperation is required because the 'SET STIMULUS' requires 7 items in payload, and the fourth and fifth items \
        is the width_ms and width_us. 

        Returns: 
            Formatted given width into millisecs and microsecs  
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
            (int): Value calculated from the input bits, this value would be given as payload.
        """
        bit_0 = UserInput.AskForIntInRange("Enter a value (0 for LOW sync line, 1 for HIGH sync line)", 0, 1) # NOTE: small style thing, dont put space at end of prompt. I went ahead and changed this 
        bit_1 = UserInput.AskForIntInRange("Enter a value for Sync Idle (0 to idle the opposite of active state, 1 to sync to idle tristate)", 0, 1) 
        bit_2 = UserInput.AskForIntInRange("Enter a value for Signal/Trigger (0 for sync to show stimulus is in progress, 1 to have sync as input triggers)", 0, 1) 
        final_value = POD_8480HR.SyncConfigBits(bit_0, bit_1, bit_2)
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
                            tab.add_row([key, val.port, stimulus_str, val.preamp, ledCurrent_str, val.ttlPullups, estimCurrent_str, val.syncConfig, ttlSetup_str]),
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
        raise Exception('[!] POD Device 8480 does not support EDF filetype.')
    

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
        

    def _StreamUntilStop(self, pod: POD_8480HR, file: IOBase) -> None :
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
                read = pod.TranslatePODpacket(pod.ReadPODpacket(timeout_sec=10)) 
                # update time by adding (dt = tf - ti)
                currentTime += (round(time.time(),9)) - t 
                # build line to write 
                data = [str(currentTime), str(read['Command Number'])]
                if('Payload' in read) :
                    data.append(str(read['Payload']))
                else :                  
                    data.append('None')
                # write to file 
                file.write(','.join(data) + '\n')
                # update initial time for next loop 
                t = (round(time.time(),9)) # initial time (sec) 
            except : 
                continue # keep looping 
            # end while 
        # streaming done
        file.close()


 

    

    

