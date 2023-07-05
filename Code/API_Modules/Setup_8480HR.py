"""
Setup_8480HR provides the setup functions for an 8480HR POD device.
"""

# enviornment imports

import copy 
from   texttable   import Texttable


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

    # ============ GLOBAL CONSTANTS ============      ========================================================================================================================
    
    
    # deviceParams keys for reference 
   # _PARAMKEYS   : list[str] = [Setup_Interface._PORTKEY,'Stimulus', 'Preamp', 'Ledcurrent', 'Estim Current', 'Sync Config', 'TTL Pullups', 'TTL Setup'] # NOTE: where are the other properties? There should be more than Stimulus. this should match the deviceParams keys.

    # for EDF file writing 
    _PHYSICAL_BOUND_uV : int = 4069 # max/-min stream value in uV

    # overwrite from parent
    _NAME : str = '8480-HR'


    # ============ PUBLIC METHODS ============      ========================================================================================================================
    
    
    @staticmethod
    def GetDeviceName() -> str : 
        # returns the name of the POD device 
        return(Setup_8480HR._NAME)
    
    def __init__(self) -> None:
        super().__init__()
        self._podParametersDict : dict[int,Params_8480HR] = {}  


    # ============ PRIVATE METHODS ============ 
    
    
    # ------------ DEVICE CONNECTION ------------


    def _ConnectPODdevice(self, deviceNum: int, deviceParams: Params_8480HR) -> bool : 
            success = False 
            # get port name 
            port = deviceParams.port.split(' ')[0] # isolate COM# from rest of string
            # create POD device 
            self._podDevices[deviceNum] = POD_8480HR(port=port)
            # test if connection is successful
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
        return(Params_8480HR(
            port              =   self._ChoosePort(forbiddenNames),
            stimulus          =    (UserInput.AskForIntInRange('Choose channel (0 or 1) for Stimulus', 0, 1),
                                    *Setup_8480HR._ChoosePeriod(),
                                    *Setup_8480HR._ChooseWidth(),
                                    UserInput.AskForInt('Enter a value for the stimulus repeat count'),
                                    Setup_8480HR._ChooseStimulusConfig()),
            preamp            =     UserInput.AskForIntInRange('Set preamp (0-1023)', 0, 1023),
            ledCurrent        =     ( UserInput.AskForIntInRange('Set ledCurrent (Hz) for CH0 (0-600)',     0, 600),
                                    UserInput.AskForIntInRange('Set ledCurrent (Hz) for CH1 (0-600)', 0, 600) ),
            ttlPullups        =     UserInput.AskForInt('Are the pullups enabled on the TTL lines? (0 for disabled, non-zero for enabled)' ),
            estimCurrent      =     (UserInput.AskForIntInRange('Set estimCurrent for Channel0  (0-100)', 0, 100),
                                    UserInput.AskForIntInRange('Set estimCurrent for Channel1  (0-100)', 0, 100)),
            syncConfig        =     Setup_8480HR._ChooseSyncConfig(),   
            ttlSetup          =    (UserInput.AskForIntInRange('Choose channel (0 or 1) for TTL Setup', 0, 1),
                                    Setup_8480HR._TtlSetup(),
                                    UserInput.AskForInt('Enter a debounce value (ms)'))
        ))
        

    @staticmethod
    def _TtlSetup() -> int:
        bit_0 = UserInput.AskForIntInRange("Enter a value (0 for rising edge triggering, 1 for falling edge)", 0, 1)
        bit_1 = UserInput.AskForIntInRange("Enter a value for stimulus triggering (0 for TTL event, 1 for TTL inputs as triggers)", 0, 1 ) # NOTE : what do 0 or 1 mean here? 
        bit_7 = UserInput.AskForIntInRange("Enter a value for TTL Input/Sync (0 for TTL operation as input, 1 for TTL pin operate as sync ouput)", 0, 1) # NOTE : what do 0 or 1 mean here? 
        ttl_value = POD_8480HR.TtlConfigBits(bit_0, bit_1, bit_7)
        return(ttl_value)
        

    @staticmethod
    def _ChooseStimulusConfig():
        bit_0 = UserInput.AskForIntInRange("Enter a value (0 for Electrical stimulus, 1 for Optical Stimulus)", 0, 1)
        bit_1 = UserInput.AskForIntInRange("Enter a value (0 for Monophasic, 1 for Biphasic)", 0, 1)
        bit_2 = UserInput.AskForIntInRange("Enter a value (0 for standard, 1 for simultaneous)", 0, 1)
        value = POD_8480HR.StimulusConfigBits(bit_0, bit_1, bit_2)
        return(value)


    @staticmethod
    def _ChooseRepeat() -> int:
        return(UserInput.AskForInt("Enter a value for the stimulus repeat count"))
    

    @staticmethod
    def _ChoosePeriod():
        user_period = UserInput.AskForFloat(("Enter a simulus period value (ms)")) # NOTE : Small style thing, dont put a space at the end of the promt. I've gone ahead and changed this her.
        period = str(user_period).split(".")
        period_ms = int(period[0])
        period_us = int(period[1])
        return(period_ms, period_us) 
    

    @staticmethod
    def _ChooseWidth():
        user_width = UserInput.AskForFloat("Enter a stimulus width value (ms)")
        width = str(user_width).split(".")
        width_ms = int(width[0])
        width_us = int(width[1])
        return(width_ms, width_us)
    

    @staticmethod
    def _ChooseSyncConfig() -> int :
        bit_0 = UserInput.AskForIntInRange("Enter a value (0 for LOW sync line, 1 for HIGH sync line)", 0, 1) # NOTE: small style thing, dont put space at end of prompt. I went ahead and changed this 
        bit_1 = UserInput.AskForIntInRange("Enter a value for Sync Idle (0 to idle the opposite of active state, 1 to sync to idle tristate)", 0, 1) # NOTE: what do 0 or 1 mean here? 
        bit_2 = UserInput.AskForIntInRange("Enter a value for Signal/Trigger (0 for sync to show stimulus is in progress, 1 to have sync as input triggers)", 0, 1) # NOTE: what do 0 or 1 mean here? 
        final_value = POD_8480HR.SyncConfigBits(bit_0, bit_1, bit_2)
        return(final_value)
    



    #     # NOTE : period_ms and width_ms are not formatted in a way that makes sense to the user. 
    #     #        (AB, CD) is not intuitive to be (ms, us). Instead, put the parts back together 
    #     #        and show AB.CD
    #     # NOTE: use title case with spaces for everything in the table. ex: channel -> Channel, period_ms -> period (ms)
    #     # NOTE: show the chanel in the table also 
    #     return(tab)
        
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
                            stimulus_str = f" Channel: {val.stimulus[0]}\n Period: {val.stimulus[1]}\n Width: {val.stimulus[2]}\n Repeat: {val.stimulus[3]}\n Config: {val.stimulus[4]}"
                            ledCurrent_str = f" Channel 1: {val.ledCurrent[0]}\n Channel 2: {val.ledCurrent[1]}\n "
                            estimCurrent_str = f" Channel 1: {val.estimCurrent[0]}\n Channel 2: {val.estimCurrent[1]}\n "
                            ttlSetup_str = f" Channel: {val.ttlSetup[0]}\n Config FLag: {val.ttlSetup[1]}\n Debounce: {val.ttlSetup[2]}\n"
                            tab.add_row([key, val.port, stimulus_str, val.preamp, ledCurrent_str, val.ttlPullups, estimCurrent_str, val.syncConfig, ttlSetup_str]),
        return(tab)






