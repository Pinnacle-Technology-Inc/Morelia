"""
Setup_8480HR provides the setup functions for an 8480HR POD device.
"""

# enviornment imports
import texttable    # NOTE: only import things that you use. Remove this. This one is imported twice.
import os           # NOTE: only import things that you use. Remove this.
import copy 
import time         # NOTE: only import things that you use. Remove this.

import numpy       as     np        # NOTE: only import things that you use. Remove this.
from   threading   import Thread    # NOTE: only import things that you use. Remove this.
from   pyedflib    import EdfWriter # NOTE: only import things that you use. Remove this.
from   io          import IOBase    # NOTE: only import things that you use. Remove this.
from   datetime    import datetime  # NOTE: only import things that you use. Remove this.
from   datetime    import date      # NOTE: only import things that you use. Remove this.
from   time        import gmtime, strftime  # NOTE: only import things that you use. Remove this.
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

# TODO replace user inputs with methods in GetUserInput 

class Setup_8480HR(Setup_Interface) : 

    # ============ GLOBAL CONSTANTS ============      ========================================================================================================================
    
    
    # deviceParams keys for reference 
    # _PARAMKEYS   : list[str] = [Setup_Interface._PORTKEY,'Stimulus','LED Current','Estim Current', 'Preamp Type', 'Sync Config ']
    _PARAMKEYS   : list[str] = [Setup_Interface._PORTKEY,'Stimulus'] # NOTE: where are the other properties? There should be more than Stimulus. this should match the deviceParams keys.
    # _LEDCURRENTKEYS : list[str] = ['EEG1','EEG2'] # Maybe not necessary
    # _ESTIMCURRENTTKEYS : list[str] = ['EEG1','EEG2'] #Not necessary

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
            self._podDevices[deviceNum].WriteRead('SET STIMULUS', (deviceParams['stimulus']['channel'], 
                                                                   *deviceParams['stimulus']['period_ms'], 
                                                                   *deviceParams['stimulus']['width_ms'], 
                                                                   deviceParams['stimulus']['repeat'], 
                                                                   deviceParams['stimulus']['config']))
            self._podDevices[deviceNum].WriteRead('SET PREAMP TYPE', (deviceParams['preamp']))

            self._podDevices[deviceNum].WriteRead('SET LED CURRENT', (0,deviceParams['ledcurrent']['EEG1']))
            self._podDevices[deviceNum].WriteRead('SET LED CURRENT', (1,deviceParams['ledcurrent']['EEG2']))
            #print("table testing", Setup_8480HR._GetPODdeviceParameterTable(self))
            self._podDevices[deviceNum].WriteRead('SET ESTIM CURRENT', (0,deviceParams['estimcurrent']['EEG1']))
            self._podDevices[deviceNum].WriteRead('SET ESTIM CURRENT', (0,deviceParams['estimcurrent']['EEG2']))
            self._podDevices[deviceNum].WriteRead('SET SYNC CONFIG', (deviceParams['Sync_Config']))
            self._podDevices[deviceNum].WriteRead('SET TTL PULLUPS', (deviceParams['ttl_pullups']))
            self._podDevices[deviceNum].WriteRead('SET TTL SETUP', (deviceParams['ttl_setup']['channel'], 
                                                                    deviceParams['ttl_setup']['ttl_config'],
                                                                    deviceParams['ttl_setup']['debounce']))
            
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
            'stimulus'      : { 'channel'    : Setup_8480HR._ChooseStimulusTypes('channel'),    # NOTE: usually for the deiceParams dict, I use title case with spaces for the dictionary keys.
                                'period_ms'  : Setup_8480HR._ChooseStimulusTypes('period_ms'),  #       What you have is completely functional! But it is good practice to keep the style consistent.  
                                'width_ms'   : Setup_8480HR._ChooseStimulusTypes('width_ms'),
                                'repeat'     : Setup_8480HR._ChooseStimulusTypes('repeat'),
                                'config'     : Setup_8480HR._ChooseStimulusTypes('config'),
                            },
            'preamp'        : Setup_8480HR._ChoosePreamp(),
            'ledcurrent'    : { 'EEG1'       : Setup_8480HR._ChooseLedCurrentforChannel('CH0'),
                                'EEG2'       : Setup_8480HR._ChooseLedCurrentforChannel('CH1'),
                            },
            'estimcurrent'  : { 'EEG1'   : Setup_8480HR._ChooseEstimCurrentforChannel("CH0"),
                                'EEG2'   : Setup_8480HR._ChooseEstimCurrentforChannel("CH1"),
                            },
            'Sync_Config'   : Setup_8480HR._ChooseSyncConfig(),
            'ttl_pullups'   : Setup_8480HR._Choosettlpullups(),
            'ttl_setup'     : { 'channel'    : Setup_8480HR._ChooseTtlSetup('channel'),
                                'ttl_config' : Setup_8480HR._ChooseTtlSetup('ttl_config'),
                                'debounce'   : Setup_8480HR._ChooseTtlSetup('debounce'),
                            }  
        }) # NOTE: try to keep the colons and spacing all in line. I've gone ahead and made the style changes.


        
    @staticmethod
    def _ChooseTtlSetup(eeg: str) -> int : # NOTE: It may be better to split this one function into three smaller functions (one for each if statement).
        try:
            if(eeg) == 'channel':
                user_channel = UserInput.AskForInt(("Choose channel for TTL Setup (0 or 1)")) # NOTE : no space acter prompt, changed this 
                return(user_channel)
            if(eeg) == 'ttl_config':
                bit_0 = UserInput.AskForIntInRange("Enter a value (0 for rising edge triggering, 1 for falling edge)", 0, 1)
                bit_1 = UserInput.AskForIntInRange("Enter a value for stimulus triggering (0 or 1)", 0, 1 ) # NOTE : what do 0 or 1 mean here? 
                bit_7 = UserInput.AskForIntInRange("Enter a value for TTL Input/Sync (0 or 1)", 0, 1) # NOTE : what do 0 or 1 mean here? 
                ttl_value = POD_8480HR.TtlConfigBits(bit_0, bit_1, bit_7)
                return(ttl_value)
            if(eeg) == 'debounce':
                debounce = UserInput. AskForInt("Enter a debounce value (ms)")
                return(debounce)
        except :
            print('[!] Please enter a valid number.')
            return (Setup_8480HR._ChooseTtlSetup(eeg))

        
    @staticmethod
    def _ChoosePreamp() -> int:
        preamp_type = UserInput.AskForIntInRange('Set Preamp value (0-1023)', 0, 1023), # NOTE: what is the unit here for (0-1023)? (ex. format as (0-1023 mA))
        return(preamp_type) # NOTE: you can combine this with the above line of code. no need to declare a varaible. 
         

    # NOTE: It may be better to split this one function into three smaller functions (one for each if statement).
    #   this _ChooseStimulusTypes function can either return one or two values, depending on the eeg input. 
    #   This is unuaual behavior for a function. So, it would be better to have multiple functions that do the different things. 
    @staticmethod
    def _ChooseStimulusTypes(eeg: str) -> int : 
        try : 
            if(eeg) == 'channel':
                user_channel = UserInput.AskForBool(("Enter a value to choose channel (0 or 1) ")) # NOTE: I was able to enter '5' and did not get an error. This needs to be fixed.
                return(user_channel)        
            if (eeg) == 'period_ms':
                user_period = UserInput.AskForFloat(("Enter a simulus period value (ms)")) # NOTE : Small style thing, dont put a space at the end of the promt. I've gone ahead and changed this her.
                period = str(user_period).split(".")
                period_ms = int(period[0])
                period_us = int(period[1])
                return(period_ms, period_us) 
            if(eeg) == 'width_ms':
                user_width = UserInput.AskForFloat("Enter a stimulus width value (ms)")
                width = str(user_width).split(".")
                width_ms = int(width[0])
                width_us = int(width[1])
                return(width_ms, width_us)
            if(eeg) == 'repeat':
                rep = UserInput.AskForInt("Enter a value for the stimulus repeat count")
                return(rep)
            if(eeg) == 'config':
                bit_0 = UserInput.AskForIntInRange("Enter a value (0 for Electrical stimulus, 1 for Optical Stimulus)", 0, 1)
                bit_1 = UserInput.AskForIntInRange("Enter a value (0 for Monophasic, 1 for Biphasic)", 0, 1)
                bit_2 = UserInput.AskForIntInRange("Enter a value (0 for standard, 1 for simultaneous) ", 0, 1)
                value = POD_8480HR.StimulusConfigBits(bit_0, bit_1, bit_2)
                return(value)
                
        except : 
            # if bad input, start over 
            print('[!] Please enter a valid number.')
            return(Setup_8480HR._ChooseStimulusTypes(eeg))
        #return(stimulus)

    
    @staticmethod
    def _ChooseLedCurrentforChannel(eeg: str) -> dict[str,int] :
        # NOTE: UserInput should handle exeptions. I dont think you need the try/except here.
        try : 
            # get ledcurrent from user 
            ledcurrent = UserInput.AskForIntInRange('Set LED Current (0-600 mA) for '+str(eeg)+' ', 0, 600) # NOTE: I made a small style change here to text. Also, Led should be LED.
        except : 
            # if bad input, start over 
            print('[!] Please enter an integer number.')
            return(Setup_8480HR._ChooseLedCurrentforChannel(eeg))
        return(ledcurrent)
    
    
    
    @staticmethod
    def _ChooseEstimCurrentforChannel(eeg: str) -> int :
        # NOTE: UserInput should handle exeptions. I dont think you need the try/except here.
        try : 
            # get ledcurrent from user 
            estimcurrent = UserInput.AskForIntInRange('Set Estim Current as a percentage (0-100) for '+str(eeg)+'', 0, 100) # NOTE: I made a small style change here to text
        except : 
            # if bad input, start over 
            print('[!] Please enter value between 0-100.')
            return(Setup_8480HR._ChooseEstimCurrentforChannel(eeg))
        return(estimcurrent)
    

    @staticmethod
    def _ChooseSyncConfig() -> int :
        bit_0 = UserInput.AskForIntInRange("Enter a value (0 for LOW sync line, 1 for HIGH sync line)", 0, 1) # NOTE: small style thing, dont put space at end of prompt. I went ahead and changed this 
        bit_1 = UserInput.AskForIntInRange("Enter a value for Sync Idle (0 or 1)", 0, 1) # NOTE: what do 0 or 1 mean here? 
        bit_2 = UserInput.AskForIntInRange("Enter a value for Signal/Trigger (0 or 1)", 0, 1) # NOTE: what do 0 or 1 mean here? 
        final_value = POD_8480HR._SyncConfigBits(bit_0, bit_1, bit_2)
        return(final_value)
    
    @staticmethod
    def _Choosettlpullups() -> int:
        # NOTE: UserInput should handle exeptions. I dont think you need the try/except here.
        try :
            pull_choice = UserInput.AskForInt('Enter value (0 for pullups disabled, non-zero for enabled)') # NOTE: this prompt is vague. Use UserInput.AskYN() instead here and ask the user something like "are TTL pullups enabled?".
            return (pull_choice)
        except : 
            # if bad input, start over 
            print('[!] Please enter an integer number.')
            return(Setup_8480HR._Choosettlpullups())
        
   

    def _IsOneDeviceValid(self, paramDict: dict) -> bool :
        # check that all params exist 
        if(list(paramDict.keys()).sort() != copy.copy(self._PARAMKEYS).sort() ) :
            raise Exception('[!] Invalid parameters for '+str(self._NAME)+'.')
        # check type of each specific command 
        if( not(
                    isinstance( paramDict[Setup_Interface._PORTKEY], str  ) 
                and isinstance( paramDict['Stimulus'],              dict  ) 
            )
        ) : 
            raise Exception('[!] Invalid paramter value types for '+str(self._NAME)+'.')
        # check that stimulus is correct
        if( list(paramDict['Stimulus'].keys()).sort() != copy.copy(self._LOWPASSKEYS).sort() ) : # NOTE: _LOWPASSKEYS is commented out, so this code wont work 
            raise Exception('[!] Invalid Stimulus parameters for '+str(self._NAME)+'.')
        # check type of stimulus
        for stimulusVal in paramDict['Stimulus'].values() : 
            if( not isinstance(stimulusVal, int) ) : 
                raise Exception('[!] Invalid Stimulus value types for '+str(self._NAME)+'.')
        # no exception raised 
        return(True)


    def _GetPODdeviceParameterTable(self) -> Texttable : 
        # setup table 
        tab = Texttable(160)
        # write column names
        tab.header(['Device #',self._PORTKEY, 'Stimulus', 'LED Current', 'Estim Current', 'Sync Config', 'TTL Pullup','Preamp', 'TTL Setup']) # NOTE: small style change 
        # write rows
        for key,val in self._podParametersDict.items() :
            tab.add_row([key, val[self._PORTKEY], '\n'.join([f"{k}: {v}" for k, v in val['stimulus'].items()]), 
                        '\n'.join([f"{k}: {v}" for k,v in val['ledcurrent'].items()]), 
                        '\n'.join([f"{k}: {v}" for k,v in val['estimcurrent'].items()]),
                        (val['Sync_Config']), 
                        (val['ttl_pullups']),
                        (val['preamp']),
                       '\n'.join([f"{k}: {v}" for k,v in val['ttl_setup'].items()]) # NOTE: nice list comprehension here! Since you do this similar code three times, 
                                                                                    #       it may be useful to put this in a function (which takes val['ttl_setup'] 
                                                                                    #       as argument ) for convinience.
                    ])
            print("key: ", key)
            print("value", val)
            print("dict",self._podParametersDict.items())
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
    
