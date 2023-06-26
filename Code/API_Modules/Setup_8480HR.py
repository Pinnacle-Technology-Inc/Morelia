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
    _PARAMKEYS   : list[str] = [Setup_Interface._PORTKEY,'stimulus', 'preamp', 'ledcurrent', 'estimcurrent', 'Sync_Config', 'ttl_pullups', 'ttl_setup'] # NOTE: where are the other properties? There should be more than Stimulus. this should match the deviceParams keys.

    # for EDF file writing 
    _PHYSICAL_BOUND_uV : int = 4069 # max/-min stream value in uV

    # overwrite from parent
    _NAME : str = '8480-HR'


    # ============ PUBLIC METHODS ============      ========================================================================================================================
    
    
    @staticmethod
    def GetDeviceName() -> str : 
        # returns the name of the POD device 
        return(Setup_8480HR._NAME)


    # ============ PRIVATE METHODS ============ 
    
    
    # ------------ DEVICE CONNECTION ------------


    def _ConnectPODdevice(self, deviceNum: int, deviceParams: dict[str,(str|int|dict[str,int])]) -> bool : 
        failed = True 
        # try : 
        # get port name 
        print("testing")
        port = deviceParams[self._PORTKEY].split(' ')[0] # isolate COM# from rest of string 
        # create POD device 
        print("testingmiddle")
        self._podDevices[deviceNum] = POD_8480HR(port=port)
        # test if connection is successful
        print("testingafter")
        if(self._TestDeviceConnection(self._podDevices[deviceNum])): 
            #write setup parameters
            self._podDevices[deviceNum].WriteRead('SET STIMULUS', (deviceParams['Stimulus']['Channel'], 
                                                                   *deviceParams['Stimulus']['Period(ms)'], 
                                                                   *deviceParams['Stimulus']['Width(ms)'], 
                                                                   deviceParams['Stimulus']['Repeat'], 
                                                                   deviceParams['Stimulus']['Config']))
            self._podDevices[deviceNum].WriteRead('SET PREAMP TYPE', (deviceParams['Preamp']))
            self._podDevices[deviceNum].WriteRead('SET LED CURRENT', (0,deviceParams['Ledcurrent']['EEG1']))
            self._podDevices[deviceNum].WriteRead('SET LED CURRENT', (1,deviceParams['Ledcurrent']['EEG2']))
            #print("table testing", Setup_8480HR._GetPODdeviceParameterTable(self))
            self._podDevices[deviceNum].WriteRead('SET ESTIM CURRENT', (0,deviceParams['Estimcurrent']['EEG1']))
            self._podDevices[deviceNum].WriteRead('SET ESTIM CURRENT', (0,deviceParams['Estimcurrent']['EEG2']))
            self._podDevices[deviceNum].WriteRead('SET SYNC CONFIG', (deviceParams['Sync Config']))
            self._podDevices[deviceNum].WriteRead('SET TTL PULLUPS', (deviceParams['Ttl Pullups']))
            self._podDevices[deviceNum].WriteRead('SET TTL SETUP', (deviceParams['Ttl Setup']['Channel'], 
                                                                    deviceParams['Ttl Setup']['Ttl Config'],
                                                                    deviceParams['Ttl Setup']['Debounce']))
            
            failed = False

        # check if connection failed 
        if(failed) :
            print('[!] Failed to connect POD device #'+str(deviceNum)+' to '+port+'.')
        else :

            print('Successfully connected POD device #'+str(deviceNum)+' to '+port+'.')
        # return True when connection successful, false otherwise
        return(not failed)


    # ------------ SETUP POD PARAMETERS ------------


    def _GetParam_onePODdevice(self, forbiddenNames: list[str]) -> dict[str,(str|int|dict[str,int])]: 
        return({
            self._PORTKEY   : Setup_8480HR._ChoosePort(forbiddenNames),
            'Stimulus'      : { 'Channel'    : Setup_8480HR._ChooseChannel('stimulus'),
                                'Period(ms)' : Setup_8480HR._ChoosePeriod(),
                                'Width(ms)'  : Setup_8480HR._ChooseWidth(),
                                'Repeat'     : Setup_8480HR._ChooseRepeat(),
                                'Config'     : Setup_8480HR._ChooseStimulusConfig(),
                            },
            'Preamp'        : Setup_8480HR._ChoosePreamp(),
            'Ledcurrent'    : { 'EEG1'       : Setup_8480HR._ChooseLedCurrentforChannel('CH0'),
                                'EEG2'       : Setup_8480HR._ChooseLedCurrentforChannel('CH1'),
                            },
            'Estimcurrent'  : { 'EEG1'       : Setup_8480HR._ChooseEstimCurrentforChannel("CH0"),
                                'EEG2'       : Setup_8480HR._ChooseEstimCurrentforChannel("CH1"),
                            },
            'Sync Config'   : Setup_8480HR._ChooseSyncConfig(),
            'Ttl Pullups'   : Setup_8480HR._Choosettlpullups(),
            'Ttl Setup'     : { 'Channel'    : Setup_8480HR._ChooseChannel('TTL Setup'),
                                'Ttl Config' : Setup_8480HR._TtlSetup(), # NOTE TTL all caps 
                                'Debounce'   : Setup_8480HR._debounce(),
                            }  
        })
        

    @staticmethod
    def _ChooseChannel(eeg: str) -> int:
        return(UserInput.AskForIntInRange('Choose channel (0 or 1) for ' + eeg, 0, 1))
    

    @staticmethod
    def _TtlSetup() -> int:
        bit_0 = UserInput.AskForIntInRange("Enter a value (0 for rising edge triggering, 1 for falling edge)", 0, 1)
        bit_1 = UserInput.AskForIntInRange("Enter a value for stimulus triggering (0 for TTL event, 1 for TTL inputs as triggers)", 0, 1 ) # NOTE : what do 0 or 1 mean here? 
        bit_7 = UserInput.AskForIntInRange("Enter a value for TTL Input/Sync (0 for TTL operation as input, 1 for TTL pin operate as sync ouput)", 0, 1) # NOTE : what do 0 or 1 mean here? 
        ttl_value = POD_8480HR.TtlConfigBits(bit_0, bit_1, bit_7)
        return(ttl_value)
    

    @staticmethod
    def _debounce():
        return(UserInput.AskForInt('Enter a debounce value (ms)'))
    
        
    @staticmethod
    def _ChoosePreamp() -> int:
        return(UserInput.AskForIntInRange('Set Preamp value (0-1023)', 0, 1023)) # NOTE: what is the unit here for (0-1023)? (ex. format as (0-1023 mA))
                     
        
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
    def _ChooseLedCurrentforChannel(eeg: str) -> dict[str,int] :
        # NOTE: UserInput should handle exeptions. I dont think you need the try/except here. 
            # get ledcurrent from user 
            return(UserInput.AskForIntInRange('Set LED Current (0-600 mA) for '+str(eeg)+' ', 0, 600))# NOTE: I made a small style change here to text. Also, Led should be LED.
 
    
    @staticmethod
    def _ChooseEstimCurrentforChannel(eeg: str) -> int :
        # NOTE: UserInput should handle exeptions. I dont think you need the try/except here.
        estimcurrent = UserInput.AskForIntInRange('Set Estim Current as a percentage (0-100) for '+str(eeg)+'', 0, 100) # NOTE: I made a small style change here to text
        return(estimcurrent)
    

    @staticmethod
    def _ChooseSyncConfig() -> int :
        bit_0 = UserInput.AskForIntInRange("Enter a value (0 for LOW sync line, 1 for HIGH sync line)", 0, 1) # NOTE: small style thing, dont put space at end of prompt. I went ahead and changed this 
        bit_1 = UserInput.AskForIntInRange("Enter a value for Sync Idle (0 to idle the opposite of active state, 1 to sync to idle tristate)", 0, 1) # NOTE: what do 0 or 1 mean here? 
        bit_2 = UserInput.AskForIntInRange("Enter a value for Signal/Trigger (0 for sync to show stimulus is in progress, 1 to have sync as input triggers)", 0, 1) # NOTE: what do 0 or 1 mean here? 
        final_value = POD_8480HR.SyncConfigBits(bit_0, bit_1, bit_2)
        return(final_value)
    

    @staticmethod
    def _Choosettlpullups() -> int:
        # NOTE: UserInput should handle exeptions. I dont think you need the try/except here.
        pull_choice = UserInput.AskForInt('Are TTL pullups enabled? (0 for pullups disabled, non-zero for enabled)') # NOTE: this prompt is vague. Use UserInput.AskYN() instead here and ask the user something like "are TTL pullups enabled?".
        return (pull_choice)
       
   
    def _IsOneDeviceValid(self, paramDict: dict) -> bool :
        if(list(paramDict.keys()).sort() != copy.copy(self._PARAMKEYS).sort() ) :
            raise Exception('[!] Invalid parameters for '+str(self._NAME)+'.')
        # check type of each specific command 
        if( not(
                    isinstance( paramDict[Setup_Interface._PORTKEY],str  ) 
                and isinstance( paramDict['Stimulus'],       dict  ) 
                and isinstance( paramDict['Led Current'],    dict  ) 
                and isinstance( paramDict['Estim Current'],  dict ) 
                and isinstance( paramDict['Sync Config'],    int ) 
                and isinstance( paramDict['TTL Pullup'],     int ) 
                and isinstance( paramDict['Preamp'],         int ) 
                and isinstance( paramDict['TTL Setup'],      dict ) 
            )
        ) : 
            raise Exception('[!] Invalid parameter value types for '+str(self._NAME)+'.')


    def _GetPODdeviceParameterTable(self) -> Texttable : 
        # setup table 
        tab = Texttable(160)
        # write column names
        tab.header(['Device #',self._PORTKEY, 'Stimulus', 'LED Current', 'Estim Current', 'Sync Config', 'TTL Pullup','Preamp', 'TTL Setup']) # NOTE: small style change 
        # write rows
        for key,val in self._podParametersDict.items() :
            tab.add_row([key, 
                        val[self._PORTKEY], 
                        '\n'.join([f"{k}: {v}" for k, v in val['Stimulus'].items()]), 
                        '\n'.join([f"{k}: {v}" for k,v in val['Ledcurrent'].items()]), 
                        '\n'.join([f"{k}: {v}" for k,v in val['Estimcurrent'].items()]),
                        (val['Sync Config']), 
                        (val['Ttl Pullups']),
                        (val['Preamp']),
                       '\n'.join([f"{k}: {v}" for k,v in val['Ttl Setup'].items()]) # NOTE: nice list comprehension here! Since you do this similar code three times, 
                                                                                    #       it may be useful to put this in a function (which takes val['ttl_setup'] 
                                                                                    #       as argument ) for convinience.
                    ])
        # NOTE : period_ms and width_ms are not formatted in a way that makes sense to the user. 
        #        (AB, CD) is not intuitive to be (ms, us). Instead, put the parts back together 
        #        and show AB.CD
        # NOTE: use title case with spaces for everything in the table. ex: channel -> Channel, period_ms -> period (ms)
        # NOTE: show the chanel in the table also 
        return(tab)
        

        # def _OpenSaveFile_TXT(self, fname: str) -> IOBase : 

        #     # open file and write column names 
        #     f = open(fname, 'w')
        #     # write time
        #     f.write( self._GetTimeHeader_forTXT() ) 
        #     # columns names
        #     f.write('\nTime,CH0,CH1,CH2\n')
        #     return(f)
    
