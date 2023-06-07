"""
Setup_8480HR provides the setup functions for an 8480HR POD device.
"""

# enviornment imports
import texttable 
import os 
import time

import numpy       as     np
from   threading   import Thread
from   pyedflib    import EdfWriter
from   io          import IOBase
from   datetime    import datetime
from   datetime    import date
from   time        import gmtime, strftime


# local imports
from Setup_PodInterface  import Setup_Interface
from PodDevice_8480HR    import POD_8480HR

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
    # _PARAMKEYS   : list[str] = [Setup_Interface._PORTKEY,'Stimulus','Led Current','Estim Current', 'Preamp Type', 'Sync Config ']
    _PARAMKEYS   : list[str] = [Setup_Interface._PORTKEY,'Stimulus','Led Current']
    # _LEDCURRENTKEYS : list[str] = ['EEG1','EEG2'] # Maybe not necessary
    # _ESTIMCURRENTTKEYS : list[str] = ['EEG1','EEG2'] #Not necessary

    # for EDF file writing 
    _PHYSICAL_BOUND_uV : int = 4069 # max/-min stream value in uV

    # overwrite from parent
    _NAME : str = '8480-HR'


    # ============ PRIVATE METHODS ============      ========================================================================================================================


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
            # write setup parameters
            print("passed")
            # self._podDevices[deviceNum].WriteRead('SET STIMULUS', deviceParams['Stimulus']                         )
            # self._podDevices[deviceNum].WriteRead('SET STIMULUS', deviceParams['Stimulus']                    )
            # self._podDevices[deviceNum].WriteRead('TYPE', deviceParams['Type']                                  )
            # self._podDevices[deviceNum].WriteRead('SET LED CURRENT', (0, deviceParams['Led Current']['CH0']     ))
            self._podDevices[deviceNum].WriteRead('RUN STIMULUS', (0))
            # self._podDevices[deviceNum].WriteRead('SET LED CURRENT', (0, deviceParams['Led Current']['CH0']    ))
            # self._podDevices[deviceNum].WriteRead('SET LED CURRENT', (1, deviceParams['Led Current']['CH1']    ))
            # self._podDevices[deviceNum].WriteRead('SET ESTIM CURRENT', (0, deviceParams['Estim Current']['EEG1']))   
            # self._podDevices[deviceNum].WriteRead('SET ESTIM CURRENT', (1, deviceParams['Estim Current']['EEG2']))   
            failed = False
        # except : 
            # fill entry 
            # self._podDevices[deviceNum] = None
    
        
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
            self._PORTKEY       :   Setup_8480HR._ChoosePort(forbiddenNames),
            # 'Led Current'       :   Setup_8480HR._ChooseLedCurrent(),
            # 'Stimulus'          :     Setup_8480HR._ChooseStimulus(),
            # 'Estim Current'     :   Setup_8480HR._ChooseEstimCurrent(),
            # 'Preamp Type'       :   Setup_8480HR._ChoosePreampType(),
            # 'Sync Config'       :   Setup_8480HR._ChooseSyncConfig()
        })
    
    

    @staticmethod
    def _ChooseStimulus() -> int :
        try : 
            # get sample rate from user 
            stimulus = int(input('Set stimulus: '))
        except : 
            # if bad input, start over 
            print('[!] Please enter an integer number.')
            return(Setup_8480HR._ChooseStimulus())
        return(stimulus)
    

    @staticmethod
    def _Type() -> int :
        try : 
            # get sample rate from user 
            type = int(input('Type: '))
        except : 
            # if bad input, start over 
            print('[!] Please enter an integer number.')
            return(Setup_8480HR._Type())
        return(type)
    
    
    @staticmethod
    def _ChooseLedCurrent() -> dict[str,int] :
        # get ledcurrent for all EEG
        return({
            'CH0'      : Setup_8480HR._ChooseLedCurrentforChannel('CH0'),
            # 'CH1'      : Setup_8480HR._ChooseLedCurrentforChannel('CH1'),
        })
    
    
    @staticmethod
    def _ChooseLedCurrentforChannel(eeg: str) -> int :
        try : 
            # get ledcurrent from user 
            ledcurrent = int(input('Set Led Current (Hz) for '+str(eeg)+': '))
        except : 
            # if bad input, start over 
            print('[!] Please enter an integer number.')
            return(Setup_8480HR._ChooseLedCurrentForEEG(eeg))
        return(ledcurrent)
    
    @staticmethod
    def _ChooseEstimCurrent() -> dict[str,int] :
        # get EstimCurrent for all EEG
        return({
            'CH0'      : Setup_8480HR._ChooseEstimCurrentforChannel('CH0'),
            'CH1'      : Setup_8480HR._ChooseEstimCurrentforChannel('CH1'),
        })
    
    
    @staticmethod
    def _ChooseEstimCurrentforChannel(eeg: str) -> int :
        try : 
            # get ledcurrent from user 
            estimcurrent = int(input('Set Estim Current (Hz) for '+str(eeg)+': '))
        except : 
            # if bad input, start over 
            print('[!] Please enter an integer number.')
            return(Setup_8480HR._ChooseEstimCurrentforChannel(eeg))
        return(estimcurrent)


    @staticmethod
    def _ChoosePreampType() -> int :
        try : 
            # get lowpass from user 
            preamp = int(input('Set preamp value from 0-1023 '+str()+': '))
        except : 
            # if bad input, start over 
            print('[!] Please enter an integer number.')
            return(Setup_8480HR._ChoosePreampType())
        # check for valid input
        if(preamp<0 or preamp>1023) : 
            print('[!] Sample rate must be between 11-500 Hz.')
            return(Setup_8480HR._ChoosePreampType())
        # return lowpass
        return(preamp)
    


    @staticmethod
    def _ChooseSyncConfig() -> int :
        try : 
            # get sample rate from user 
            sync = int(input('Set Sync Config: '))
        except : 
            # if bad input, start over 
            print('[!] Please enter an integer number.')
            return(Setup_8480HR._ChooseSyncConfig())
        return(sync)