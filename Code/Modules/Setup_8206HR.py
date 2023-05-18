"""
Setup_8206HR provides the setup functions for an 8206-HR POD device.
"""

# enviornment imports
import texttable
import threading 
from   pyedflib import EdfWriter as edfw
from   os       import path      as osp
import numpy                     as np

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
    _LOWPASSKEYS = ['EEG1','EEG2','EEG3/EMG'] # TODO reference this 

    _PHYSICAL_BOUND_uV = 4069 # max/-min stream value in uV

    _NAME = '8206-HR'
    _PORTKEY = _PARAMKEYS[0] # 'Port'


    # ============ PRIVATE METHODS ============      ========================================================================================================================


    # ------------ DEVICE CONNECTION ------------


    def _ConnectPODdevice(self, deviceNum : int, deviceParams : dict) : 
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


    def _GetParam_onePODdevice(self, forbiddenNames : list) : 
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
    def _ChooseLowpassForEEG(eeg : str):
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
        print('\nParameters for all '+str(self._NAME)+' Devices:')
        # setup table 
        tab = texttable.Texttable()
        # write column names
        tab.header(['Device #','Port','Sample Rate (Hz)', 'Preamplifier Gain', 'EEG1 Low Pass (Hz)','EEG2 Low Pass (Hz)','EEG3/EMG Low Pass (Hz)'])
        # write rows
        for key,val in self._podParametersDict.items() :
            tab.add_row([key, val['Port'], val['Sample Rate'], val['Preamplifier Gain'], val['Low Pass']['EEG1'], val['Low Pass']['EEG2'], val['Low Pass']['EEG3/EMG'],])
        # show table 
        print(tab.draw())


    # ------------ FILE HANDLING ------------


    @staticmethod
    def _OpenSaveFile_TXT(fname) : 
        # open file and write column names 
        f = open(fname, 'w')
        f.write('time,ch0,ch1,ch2\n')
        return(f)
    
    def _OpenSaveFile_EDF(self, fname, devNum):
        # create file
        f = edfw(fname, 3) 
        # get info for each channel
        for i in range(len(self._LOWPASSKEYS)):
            f.setSignalHeader( i, {
                'label' : self._LOWPASSKEYS[i],
                'dimension' : 'uV',
                'sample_rate' : self._podParametersDict[devNum]['Sample Rate'],
                'physical_max': self._PHYSICAL_BOUND_uV,
                'physical_min': -self._PHYSICAL_BOUND_uV, 
                'digital_max': 32767, 
                'digital_min': -32768, 
                'transducer': '', 
                'prefilter': ''            
            } )
        return(f)


    @staticmethod
    def _WriteDataToFile_TXT(file, data : list, sampleRate : int, t : int) : 
        # initialize times
        dt = 1.0 / sampleRate
        ti = t
        # save data for each timestamp
        for i in range(len(data[0])) : 
            # increment time, rounding to 6 decimal places
            ti = round(ti+dt, 6)  
            # build line to write 
            line = [ ti, data[0][i], data[1][i], data[2][i] ]
            # convert data into comma separated string
            line = ','.join(str(x) for x in line) + '\n'
            # write data to file 
            file.write(line)


    @staticmethod
    def _WriteDataToFile_EDF(file, data) : 
        # write data to EDF file 
        file.writeSamples(data)


    # ------------ STREAM ------------ 


    def _StreamThreading(self) :
        # create save files for pod devices
        podFiles = {devNum: self._OpenSaveFile(devNum) for devNum in self._podDevices.keys()}
        # make threads for reading 
        readThreads = {
            # create thread to _StreamUntilStop() to dictionary entry devNum
            devNum : threading.Thread(
                    target = self._StreamUntilStop, 
                    args = ( pod, file, params['Sample Rate'] )
                )
            # for each device 
            for devNum,params,pod,file in 
                zip(
                    self._podParametersDict.keys(),     # devNum
                    self._podParametersDict.values(),   # params
                    self._podDevices.values(),          # pod
                    podFiles.values()                   # file
                ) 
        }
        for t in readThreads.values() : 
            # start streaming (program will continue until .join() or streaming ends)
            t.start()
        return(readThreads)
    
    
    def _StreamUntilStop(self, pod : POD_8206HR, file, sampleRate : int):
        # get file type
        name, ext = osp.splitext(self._saveFileName)
        # packet to mark stop streaming 
        stopAt = pod.GetPODpacket(cmd='STREAM', payload=0)  
        # start streaming from device  
        pod.WriteRead(cmd='STREAM', payload=1)
        # track time (second)
        t = 0
        if(ext=='.edf'): file.writeAnnotation(t, -1, "Start")
        while(True):
            # initialize data array 
            data0 = np.zeros(sampleRate)
            data1 = np.zeros(sampleRate)
            data2 = np.zeros(sampleRate)
            # read data for one second
            for i in range(sampleRate):
                # read once 
                r = pod.ReadPODpacket()
                # stop looping when stop stream command is read 
                if(r == stopAt) : 
                    if(ext=='.edf'): file.writeAnnotation(t, -1, "Stop")
                    file.close()
                    return  ##### END #####
                # translate 
                rt = pod.TranslatePODpacket(r)
                # save data as uV
                data0[i] = self._uV(rt['Ch0'])
                data1[i] = self._uV(rt['Ch1'])
                data2[i] = self._uV(rt['Ch2'])
            # save to file 
            if(ext=='.csv' or ext=='.txt') : self._WriteDataToFile_TXT(file, [data0,data1,data2], sampleRate, t)
            elif(ext=='.edf') :              self._WriteDataToFile_EDF(file, [data0,data1,data2])
            # increment by second 
            t+=1

            
    def _StopStream(self):
        # tell devices to stop streaming 
        for pod in self._podDevices.values() : 
            pod.WritePacket(cmd='STREAM', payload=0)


    # ------------ HELPER ------------


    @staticmethod
    def _uV(voltage):
        # round to 6 decimal places... add 0.0 to prevent negative zeros when rounding
        return ( round(voltage * 1E-6, 6 ) + 0.0 )