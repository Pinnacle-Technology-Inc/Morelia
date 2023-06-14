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
    _PARAMKEYS   : list[str] = [Setup_Interface._PORTKEY,'Stimulus']
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
           
            self._podDevices[deviceNum].WriteRead('SET STIMULUS', (0, deviceParams['stimulus']['period_ms'],['period_us'],['width_ms'],['width_us'],['repeat'],['config']  ))
           
            #self._podDevices[deviceNum].WriteRead('SET STIMULUS', (1, deviceParams['period_ms'],['period_us'],['width_ms'],['width_us'],['repeat'],['config']  ))

            self._podDevices[deviceNum].WriteRead('RUN STIMULUS', (0))

            #self._podDevices[deviceNum].WriteRead('SET STIMULUS', (0, deviceParams['Stimulus']['Ch0']           ))
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
            self._PORTKEY         :   Setup_8480HR._ChoosePort(forbiddenNames),
            'Stimulus'            :   Setup_8480HR._ChooseStimulus(),
            # 'Led Current'       :   Setup_8480HR._ChooseLedCurrent(),
            # 'Estim Current'     :   Setup_8480HR._ChooseEstimCurrent(),
            # 'Preamp Type'       :   Setup_8480HR._ChoosePreampType(),
            # 'Sync Config'       :   Setup_8480HR._ChooseSyncConfig()
        })

        
    @staticmethod
    def _ChooseStimulus() -> dict[str,int] :
        # get ledcurrent for all EEG
        return({
            # 'ch0'         : Setup_8480HR._ChooseStimulusTypes('EEG1'),
            #'ch1'         : Setup_8480HR._ChooseStimulusTypes('ch1'),
            # 'period_ms'     : Setup_8480HR._ChooseStimulusTypes('period_ms'),
            # 'period_us'     : Setup_8480HR._ChooseStimulusTypes('period_us'),
            # 'width_ms'      : Setup_8480HR._ChooseStimulusTypes('width_ms'),
            # 'width_us'      : Setup_8480HR._ChooseStimulusTypes('width_us'),
            # 'repeat'        : Setup_8480HR._ChooseStimulusTypes('repeat'),
            'config'        : Setup_8480HR._ChooseStimulusTypes('config'),
        })



    @staticmethod
    def _ChooseStimulusTypes(eeg: str) -> int :
        try : 
            # get ledcurrent from user 
            #stimulus = int(input('Set Stimulus '+str(eeg)+': '))
            #if (eeg) == 'period_ms':  
            
            if (eeg) == 'period_ms':
                user_period = float(input("Enter a Stimulus period value(milliseconds): "))
                period = str(user_period).split(".")
                period_ms = int(period[0])
                period_us = int(period[1])
                print(period_ms)
                return(period_ms)
                
            if (eeg) == 'period_us':
                user_period = float(input("Enter a Stimulus period value(milliseconds): "))
                period = str(user_period).split(".")
                period_ms = int(period[0])
                period_us = int(period[1])
                print(period_us)
                return(period_us)
            if(eeg) == 'width_ms':
                user_width = float(input("Enter a Stimulus width value(milliseconds): "))
                width = str(user_width).split(".")
                width_ms = int(width[0])
                width_us = int(width[1])
                print(width_ms)
                return(width_ms)
            if(eeg) == 'width_us':
                user_width = float(input("Enter a Stimulus width value(milliseconds): "))
                width = str(user_width).split(".")
                width_ms = int(width[0])
                width_us = int(width[1])
                print(width_us)
                return(width_us)
            if(eeg) == 'repeat':
                rep = int(input("Enter a value for Stimulus Repeat Count: "))
                return(rep)
            if(eeg) == 'config':
                list = []
                bit_2 = int(input("Enter a value(0 for standard, 1 for simultaneous):  "))
                bit_1 = int(input("Enter a value(0 for Monophasic, 1 for Biphasic): "))
                bit_0 = int(input("Enter a value(0 for Electrical stimulus, 1 for Optical Stimulus): "))
                
                



        except : 
            # if bad input, start over 
            print('[!] Please enter a valid number.')
            return(Setup_8480HR._ChooseStimulusTypes(eeg))
        #return(stimulus)

   


    @staticmethod
    def _ChooseLedCurrent() -> dict[str,int] :
        # get ledcurrent for all EEG
        return({
            'CH0'      : Setup_8480HR._ChooseLedCurrentforChannel('CH0'),
            #'CH1'      : Setup_8480HR._ChooseLedCurrentforChannel('CH1'),
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