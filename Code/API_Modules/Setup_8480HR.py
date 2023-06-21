"""
Setup_8480HR provides the setup functions for an 8480HR POD device.
"""

# enviornment imports
import texttable 
import os
import copy 
import time

import numpy       as     np
from   threading   import Thread
from   pyedflib    import EdfWriter
from   io          import IOBase
from   datetime    import datetime
from   datetime    import date
from   time        import gmtime, strftime
from   texttable   import Texttable


# local imports
from Setup_PodInterface  import Setup_Interface
from PodDevice_8480HR    import POD_8480HR
from GetUserInput       import UserInput

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
    # _PARAMKEYS   : list[str] = [Setup_Interface._PORTKEY,'Stimulus','Led Current','Estim Current', 'Preamp Type', 'Sync Config ']
    _PARAMKEYS   : list[str] = [Setup_Interface._PORTKEY,'Stimulus']
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
            self._PORTKEY        :  Setup_8480HR._ChoosePort(forbiddenNames),
            'stimulus'      : {
                    'channel'    : Setup_8480HR._ChooseStimulusTypes('channel'),
                    'period_ms'  : Setup_8480HR._ChooseStimulusTypes('period_ms'),
                    'width_ms'   : Setup_8480HR._ChooseStimulusTypes('width_ms'),
                    'repeat'     : Setup_8480HR._ChooseStimulusTypes('repeat'),
                    'config'     : Setup_8480HR._ChooseStimulusTypes('config'),
                },
            'ledcurrent'     : {
                    'EEG1'       : Setup_8480HR._ChooseLedCurrentforChannel('CH0'),
                    'EEG2'       : Setup_8480HR._ChooseLedCurrentforChannel('CH1'),
                },
                       
            'estimcurrent' : {
                        'EEG1'   :    Setup_8480HR._ChooseEstimCurrentforChannel("CH0"),
                        'EEG2'   :    Setup_8480HR._ChooseEstimCurrentforChannel("CH1"),
            },
            
            'Sync_Config'        :   Setup_8480HR._ChooseSyncConfig(),
            'ttl_pullups'        :   Setup_8480HR._Choosettlpullups(),
            'ttl_setup'   : {
                    'channel'    :    Setup_8480HR._ChooseTtlSetup('channel'),
                    'ttl_config' :    Setup_8480HR._ChooseTtlSetup('ttl_config'),
                    'debounce'   :    Setup_8480HR._ChooseTtlSetup('debounce'),
            }  
        })


        
    @staticmethod
    def _ChooseTtlSetup(eeg: str) -> int :
        try:
            if(eeg) == 'channel':
                user_channel = UserInput.AskForInt(("Enter a value to choose channel (0 or 1) "))
                return(user_channel)
            if(eeg) == 'ttl_config':
                bit_0 = bool(int(input("Enter a value (0 for rising edge triggering, 1 for falling edge): ")))
                bit_1 = bool(int(input("Enter a value for stimulus triggering: " )))
                bit_7 = bool(int(input("Enter a value for TTL Input/Sync(0 or 1): ")))
                ttl_value = POD_8480HR.TtlConfigBits(bit_0, bit_1, bit_7)
                return(ttl_value)
            if(eeg) == 'debounce':
                debounce = int(input("Enter a debounce value (ms) : "))
                return(debounce)
        except :
            print('[!] Please enter a valid number.')
            return (Setup_8480HR._ChooseTtlSetup(eeg))

    


    @staticmethod
    def _ChooseStimulusTypes(eeg: str) -> int :
        try : 
            if(eeg) == 'channel':
                user_channel = UserInput.AskForInt(("Enter a value to choose channel (0 or 1) "))
                return(user_channel)        
            if (eeg) == 'period_ms':
                user_period = UserInput.AskForFloat(("Enter a Stimulus period value (ms) "))
                period = str(user_period).split(".")
                period_ms = int(period[0])
                period_us = int(period[1])
                return(period_ms, period_us)
            if(eeg) == 'width_ms':
                user_width = UserInput.AskForFloat("Enter a Stimulus width value (ms) ")
                width = str(user_width).split(".")
                width_ms = int(width[0])
                width_us = int(width[1])
                return(width_ms, width_us)
            if(eeg) == 'repeat':
                rep = UserInput.AskForInt("Enter a value for Stimulus Repeat Count ")
                return(rep)
            if(eeg) == 'config':
                bit_0 = bool(int(input("Enter a value (0 for Electrical stimulus, 1 for Optical Stimulus) : ")))
                bit_1 = bool(int(input("Enter a value (0 for Monophasic, 1 for Biphasic) : ")))
                bit_2 = bool(int(input("Enter a value (0 for standard, 1 for simultaneous) :  ")))
                value = POD_8480HR.StimulusConfigBits(bit_0, bit_1, bit_2)
                return(value)
                
        except : 
            # if bad input, start over 
            print('[!] Please enter a valid number.')
            return(Setup_8480HR._ChooseStimulusTypes(eeg))
        #return(stimulus)

    
    @staticmethod
    def _ChooseLedCurrentforChannel(eeg: str) -> dict[str,int] :
        try : 
            # get ledcurrent from user 
            ledcurrent = UserInput.AskForIntInRange('Set Led Current from(0-600)mA for '+str(eeg)+' ',     0, 600)
        except : 
            # if bad input, start over 
            print('[!] Please enter an integer number.')
            return(Setup_8480HR._ChooseLedCurrentforChannel(eeg))
        return(ledcurrent)
    
    
    
    @staticmethod
    def _ChooseEstimCurrentforChannel(eeg: str) -> int :
        try : 
            # get ledcurrent from user 
            estimcurrent = UserInput.AskForIntInRange('Set Estim Current (0-100) as a percentage for '+str(eeg)+'',     0, 100)
        except : 
            # if bad input, start over 
            print('[!] Please enter value between 0-100.')
            return(Setup_8480HR._ChooseEstimCurrentforChannel(eeg))
        return(estimcurrent)
    

    @staticmethod
    def _ChooseSyncConfig() -> int :
        bit_0 = bool(int(input("Enter a value (0 for LOW sync line, 1 for HIGH sync line) : ")))
        bit_1 = bool(int(input("Enter a value for Sync Idle(0 or 1) : ")))
        bit_2 = bool(int(input("Enter a value for Signal/Trigger(0 or 1) : ")))
        final_value = POD_8480HR._SyncConfigBits(bit_0, bit_1, bit_2)
        return(final_value)
    
    @staticmethod
    def _Choosettlpullups() -> int:
        try :
            pull_choice = int(input('Enter value (0 for pullups disabled, non-zero for enabled) '+str()+' : '))
        except : 
            # if bad input, start over 
            print('[!] Please enter an integer number.')
            return(Setup_8480HR._Choosettlpullups())
        return (pull_choice)
   

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
        if( list(paramDict['Stimulus'].keys()).sort() != copy.copy(self._LOWPASSKEYS).sort() ) : 
            raise Exception('[!] Invalid Stimulus parameters for '+str(self._NAME)+'.')
        # check type of stimulus
        for stimulusVal in paramDict['Stimulus'].values() : 
            if( not isinstance(stimulusVal, int) ) : 
                raise Exception('[!] Invalid Stimulus value types for '+str(self._NAME)+'.')
        # no exception raised 
        return(True)


    # def _GetPODdeviceParameterTable(self) -> Texttable : 
    #     # setup table 
    #     tab = Texttable(160)
    #     # write column names
    #     tab.header(['Device #',self._PORTKEY, 'Stimulus', 'Ledcurrent', 'Estim Current', 'Sync Config', 'TTL Pullup', 'TTL Setup'])
    #     # write rows
    #     for key,val in self._podParametersDict.items() :
    #         tab.add_row([key, val[self._PORTKEY], '\n'.join([f"{k}: {v}" for k, v in val['stimulus'].items()]), 
    #                     '\n'.join([f"{k}: {v}" for k,v in val['ledcurrent'].items()]), 
    #                     '\n'.join([f"{k}: {v}" for k,v in val['estimcurrent'].items()]),
    #                     (val['Sync_Config']), 
    #                     (val['ttl_pullups']),
    #                     '\n'.join([f"{k}: {v}" for k,v in val['ttl_setup'].items()])
    #                 ])
    #         print("key: ", key)
    #         print("value", val)
    #         print("dict",self._podParametersDict.items())
    #     return(tab)
        

