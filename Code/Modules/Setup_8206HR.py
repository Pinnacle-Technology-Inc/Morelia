"""
Setup_8206HR provides the setup functions for an 8206-HR POD device.
"""

# enviornment imports
import texttable

# local imports
from Setup_PodInterface  import Setup_Interface
from PodDevice_8206HR    import POD_8206HR 


# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Setup_8206HR(Setup_Interface) : 

    # ============ GLOBAL CONSTANTS ============      ========================================================================================================================
    

    _PARAMKEYS = ['Port','Sample Rate','Preamplifier Gain','Low Pass'] # TODO reference this 
    _EEGKEYS = ['EEG1','EEG2','EEG3/EMG'] # TODO reference this 

    _NAME = '8206-HR'
    _PORTKEY = _PARAMKEYS[0] # 'Port'


    # ============ PRIVATE METHODS ============      ========================================================================================================================


    # ------------ DEVICES ------------


    def _ConnectPODdevice(self, deviceNum, deviceParams) : 
        failed = True 
        try : 
            # get port name 
            port = deviceParams['Port'].split(' ')[0] # isolate COM# from rest of string
            # create POD device 
            self._podDevices[deviceNum] = POD_8206HR(port=port, preampGain=deviceParams['Preamplifier Gain'])
            # test if connection is successful
            if(self._TestDeviceConnection(self._podDevices[deviceNum])):
                # write setup parameters
                self._podDevices[deviceNum].WriteRead('SET SAMPLE RATE', deviceParams['Sample Rate'])
                self._podDevices[deviceNum].WriteRead('SET LOWPASS', (0, deviceParams['Low Pass']['EEG1']))
                self._podDevices[deviceNum].WriteRead('SET LOWPASS', (1, deviceParams['Low Pass']['EEG2']))
                self._podDevices[deviceNum].WriteRead('SET LOWPASS', (2, deviceParams['Low Pass']['EEG3/EMG']))   
                failed = False
        except : 
            # fill entry 
            self._podDevices[deviceNum] = None

        # check if connection failed 
        if(failed) :
            print('Failed to connect POD device #'+str(deviceNum)+' to '+port+'.')
        else :
            print('Successfully connected POD device #'+str(deviceNum)+' to '+port+'.')
        # return True when connection successful, false otherwise
        return(not failed)


    # ------------ SETUP POD PARAMETERS ------------


    def _GetParam_onePODdevice(self, forbiddenNames) : 
        return({
            'Port'              : Setup_8206HR._ChoosePort(forbiddenNames),
            'Sample Rate'       : Setup_8206HR._ChooseSampleRate(),
            'Preamplifier Gain' : Setup_8206HR._ChoosePreampGain(),
            'Low Pass'          : Setup_8206HR._ChooseLowpass()
        })
    

    @staticmethod
    def _ChooseSampleRate():
        try : 
            # get sample rate from user 
            sampleRate = int(input('Set sample rate (Hz): '))
        except : 
            # if bad input, start over 
            print('[!] Please enter an integer number.')
            return(Setup_8206HR._ChooseSampleRate())
        # check for valid input
        if(sampleRate<100 or sampleRate>2000) : 
            print('[!] Sample rate must be between 100-2000.')
            return(Setup_8206HR._ChooseSampleRate())
        # return sample rate
        return(sampleRate)
    

    @staticmethod
    def _ChoosePreampGain():
        try:
            # get gain from user 
            gain = int(input('Set preamplifier gain: '))
        except : 
            # if bad input, start over 
            print('[!] Please enter an integer number.')
            return(Setup_8206HR._ChoosePreampGain())
        # check for valid input 
        if(gain != 10 and gain != 100):
            # prompt again 
            print('[!] Preamplifier gain must be 10 or 100.')
            return(Setup_8206HR._ChoosePreampGain())
        # return preamplifier gain 
        return(gain)
    

    @staticmethod
    def _ChooseLowpass():
        # get lowpass for all EEG
        return({
            'EEG1'      : Setup_8206HR._ChooseLowpassForEEG('EEG1'),
            'EEG2'      : Setup_8206HR._ChooseLowpassForEEG('EEG2'),
            'EEG3/EMG'  : Setup_8206HR._ChooseLowpassForEEG('EEG3/EMG'),
        })
    
    
    @staticmethod
    def _ChooseLowpassForEEG(eeg):
        try : 
            # get lowpass from user 
            lowpass = int(input('Set lowpass (Hz) for '+str(eeg)+': '))
        except : 
            # if bad input, start over 
            print('[!] Please enter an integer number.')
            return(Setup_8206HR._ChooseLowpassForEEG(eeg))
        # check for valid input
        if(lowpass<11 or lowpass>500) : 
            print('[!] Sample rate must be between 11-500 Hz.')
            return(Setup_8206HR._ChooseLowpassForEEG(eeg))
        # return lowpass
        return(lowpass)


    # ------------ DISPLAY POD PARAMETERS ------------


    def _DisplayPODdeviceParameters(self) : 
        # print title 
        print('\nParameters for all POD Devices:')
        # setup table 
        tab = texttable.Texttable()
        # write column names
        tab.header(['Device #','Port','Sample Rate (Hz)', 'Preamplifier Gain', 'EEG1 Low Pass (Hz)','EEG2 Low Pass (Hz)','EEG3/EMG Low Pass (Hz)'])
        # write rows
        for key,val in self._podParametersDict.items() :
            tab.add_row([key, val['Port'], val['Sample Rate'], val['Preamplifier Gain'], val['Low Pass']['EEG1'], val['Low Pass']['EEG2'], val['Low Pass']['EEG3/EMG'],])
        # show table 
        print(tab.draw())

            
    ###############################################
    # WORKING 
    ###############################################