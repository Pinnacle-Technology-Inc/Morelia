"""
Setup_8401HR provides the setup functions for an 8206-HR POD device.
REQUIRES FIRMWARE 1.0.2 OR HIGHER.
"""

# enviornment imports
import copy
import os 
import time 
import numpy       as     np
from   texttable    import Texttable
from   threading    import Thread
from   io           import IOBase
from   pyedflib     import EdfWriter

# local imports
from Setup_PodInterface import Setup_Interface
from PodDevice_8401HR   import POD_8401HR 
from GetUserInput       import UserInput

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Setup_8401HR(Setup_Interface) : 
    
    # ============ GLOBAL CONSTANTS ============      ========================================================================================================================
    

    _PARAMKEYS = [Setup_Interface._PORTKEY,'Preamplifier Device','Sample Rate','Mux Mode','Preamplifier Gain','Second Stage Gain','High-pass','Low-pass','Bias','DC Mode']
    _CHANNELKEYS = ['A','B','C','D']

    # for EDF file writing 
    _PHYSICAL_BOUND_uV : int = 4069 # max/-min stream value in uV # TODO is this same as 8206HR???

    # overwrite from parent
    _NAME : str = '8401-HR'


    # ============ PUBLIC METHODS ============      ========================================================================================================================


    @staticmethod
    def GetDeviceName() -> str : 
        # returns the name of the POD device 
        return(Setup_8401HR._NAME)
    

    # ============ PRIVATE METHODS ============      ========================================================================================================================


    # ------------ DEVICE CONNECTION ------------


    def _ConnectPODdevice(self, deviceNum: int, deviceParams: dict[str,(str|int|dict)]) -> bool : 
        failed = True 
        try : 
            # get port name 
            port = deviceParams[self._PORTKEY].split(' ')[0] # isolate COM# from rest of string
            # create POD device 
            self._podDevices[deviceNum] = POD_8401HR(
                port        = port, 
                preampName  = deviceParams['Preamplifier Device'], 
                ssGain      = deviceParams['Second Stage Gain'],
                preampGain  = deviceParams['Preamplifier Gain'],
            )
            # test if connection is successful
            if(self._TestDeviceConnection(self._podDevices[deviceNum])):
                # write devicesetup parameters
                self._podDevices[deviceNum].WriteRead('SET SAMPLE RATE', deviceParams['Sample Rate'])
                self._podDevices[deviceNum].WriteRead('SET MUX MODE', int(deviceParams['Mux Mode'])) # bool to int 
                # write channel specific setup parameters
                channels = ['A','B','C','D']
                for i, letter in enumerate(channels, start=0) : 
                    if(deviceParams['High-pass'][letter] != None) : self._podDevices[deviceNum].WriteRead('SET HIGHPASS', (i, self._CodeHighpass(deviceParams['High-pass'][letter])))
                    if(deviceParams['Low-pass' ][letter] != None) : self._podDevices[deviceNum].WriteRead('SET LOWPASS',  (i, deviceParams['Low-pass'][letter]))
                    if(deviceParams['DC Mode'  ][letter] != None) : self._podDevices[deviceNum].WriteRead('SET DC MODE',  (i, self._CodeDCmode(deviceParams['DC Mode'][letter])))
                    self._podDevices[deviceNum].WriteRead('SET SS CONFIG', (i, POD_8401HR.GetSSConfigBitmask_int(gain=deviceParams['Second Stage Gain'][letter], highpass=deviceParams['High-pass'][letter])))

                # successful write if no exceptions raised 
                failed = False
        except : # except Exception as e : print('[!]', e)            
            # fill entry 
            self._podDevices[deviceNum] = None
        # check if connection failed 
        if(failed) : print('[!] Failed to connect POD device #'+str(deviceNum)+' to '+port+'.')
        else : print('Successfully connected POD device #'+str(deviceNum)+' to '+port+'.')
        # return True when connection successful, false otherwise
        return(not failed)
    

    @staticmethod
    def _CodeHighpass(highpass) : 
        match highpass : 
            case  0.5  : return(0)
            case  1.0  : return(1)
            case 10.0  : return(2)
            case  0.0  : return(3)
            case _ : raise Exception('[!] High-pass of '+str(highpass)+' Hz is not supported.')


    @staticmethod
    def _CodeDCmode(dcMode) : 
        match dcMode : 
            case 'VBIAS' : return(0)
            case 'AGND'  : return(1)
            case _ : raise Exception('[!] DC Mode \''+str(dcMode)+'\' is not supported.')


    # ------------ SETUP POD PARAMETERS ------------


    def _GetParam_onePODdevice(self, forbiddenNames: list[str]) -> dict[str,(str|int|dict)] :
        params = {
            self._PORTKEY           : self._ChoosePort(forbiddenNames),
            'Preamplifier Device'   : self._GetPreampDeviceName(),
            'Sample Rate'           : UserInput.AskForIntInRange('Set sample rate (Hz)', 2000, 20000),
            'Mux Mode'              : UserInput.AskYN('Use mux mode?')
        }
        # get channel map for the user's preamplifier 
        chmap = POD_8401HR.GetChannelMapForPreampDevice(params['Preamplifier Device'])
        # get parameters for each channel (A,B,C,D)
        params['Preamplifier Gain'] = self._SetForMappedChannels('Set preamplifier gain (1, 10, or 100) for...',        chmap, self._SetPreampGain  )
        params['Second Stage Gain'] = self._SetForMappedChannels('Set second stage gain (1 or 5) for...',               chmap, self._SetSSGain      )
        params['High-pass']         = self._SetForMappedChannels('Set high-pass filter (0, 0.5, 1, or 10 Hz) for...',   chmap, self._SetHighpass    )
        params['Low-pass']          = self._SetForMappedChannels('Set low-pass filter (21-15000 Hz) for...',            chmap, self._SetLowpass     )
        params['Bias']              = self._SetForMappedChannels('Set bias (+/- 2.048 V) for...',                       chmap, self._SetBias        )
        params['DC Mode']           = self._SetForMappedChannels('Set DC mode (VBIAS or AGND) for...',                  chmap, self._SetDCMode      )
        return(params)


    def _GetPreampDeviceName(self) -> str : 
        deviceList = POD_8401HR.GetSupportedPreampDevices()
        return( UserInput.AskForStrInList(
            prompt='Set mouse/rat preamplifier',
            goodInputs=deviceList,
            badInputMessage='[!] Please input a valid mouse/rat preamplifier '+str(tuple(deviceList))+'.'))

        
    def _SetForMappedChannels(self, message: str, channelMap: dict[str,str], func: 'function') -> dict[str,int|None]: # func MUST take one argument, which is the channel map value 
        print(message)
        preampDict = {}
        for abcd, label in channelMap.items() : 
            # automatically set to None if no-connect (NC)
            if(label == 'NC') : 
                preampDict[abcd] = None
            # otherwise, ask for input 
            else: 
                preampDict[abcd] = func(label)
        return(preampDict)
    

    @staticmethod
    def _SetPreampGain(channelName: str) -> int|None: 
        gain = UserInput.AskForIntInList(
            prompt='\t'+str(channelName), 
            goodInputs=[1,10,100], 
            badInputMessage='[!] For EEG/EMG, the gain must be 10 or 100. For biosensors, the gain is 1 (None).')
        if(gain == 1) : 
            return(None)
        return(gain)
        

    @staticmethod
    def _SetSSGain(channelName: str) -> int|None : 
        return( UserInput.AskForIntInList(
            prompt='\t'+str(channelName), 
            goodInputs=[1,5], 
            badInputMessage='[!] The gain must be 1 or 5.') )


    @staticmethod
    def _SetHighpass(channelName: str) -> int|None : 
        # NOTE  SET HIGHPASS Sets the highpass filter for a channel (0-3). 
        #       Requires channel to set, and filter value (0-3): 
        #       0 = 0.5Hz, 1 = 1Hz, 2 = 10Hz, 3 = DC / No Highpass 
        # NOTE  be sure to convert the input value to a number key usable by the device!
        hp = UserInput.AskForFloatInList(
            prompt='\t'+str(channelName),
            goodInputs=[0,0.5,1,10],
            badInputMessage='[!] The high-pass filter must be 0.5, 1, or 10 Hz. If the channel is DC, input 0.' )
        if(hp == 0) :
            return(None)
        return(hp)


    @staticmethod
    def _SetLowpass(channelName: str) -> int|None : 
        return(UserInput.AskForIntInRange(
            prompt='\t'+str(channelName), 
            minimum=21, maximum=15000, 
            thisIs='The low-pass filter', unit=' Hz' ))
    
    
    @staticmethod
    def _SetBias(channelName: str) -> float : 
        return( UserInput.AskForFloatInRange(
            prompt='\t'+str(channelName),
            minimum=-2.048,
            maximum=2.048,
            thisIs='The bias', unit=' V (default is 0.6 V)'
        ))
    

    @staticmethod
    def _SetDCMode(channelName: str) -> str : 
        # NOTE  SET DC MODE Sets the DC mode for the selected channel. 
        #       Requires the channel to read, and value to set: 
        #       0 = Subtract VBias, 1 = Subtract AGND.  
        #       Typically 0 for Biosensors, and 1 for EEG/EMG
        # NOTE  be sure to convert the input value to a number key usable by the device!
        return( UserInput.AskForStrInList(
            prompt='\t'+str(channelName),
            goodInputs=['VBIAS','AGND'],
            badInputMessage='[!] The DC mode must subtract VBIAS or AGND. Typically, Biosensors are VBIAS and EEG/EMG are AGND.' ))



    # ------------ DISPLAY POD PARAMETERS ------------


    def _GetPODdeviceParameterTable(self) -> Texttable : 
        # setup table 
        tab = Texttable(160)
        # write column names
        tab.header(['Device #',self._PORTKEY,'Preamplifier Device',
                    'Sample Rate (Hz)','Mux Mode', 'Preamplifier Gain','Second Stage Gain',
                    'High-pass (Hz)','Low-pass (Hz)','Bias (V)','DC Mode'])
        # for each device 
        for key,val in self._podParametersDict.items() :
            # get channel mapping for device 
            chmap = POD_8401HR.GetChannelMapForPreampDevice(val['Preamplifier Device'])
            # write row to table 
            tab.add_row([
                key, val[self._PORTKEY], val['Preamplifier Device'], val['Sample Rate'],str(val['Mux Mode']),
                self._NiceABCDtableText(val['Preamplifier Gain'],   chmap),
                self._NiceABCDtableText(val['Second Stage Gain'],   chmap),
                self._NiceABCDtableText(val['High-pass'],           chmap),
                self._NiceABCDtableText(val['Low-pass'],            chmap),
                self._NiceABCDtableText(val['Bias'],                chmap),
                self._NiceABCDtableText(val['DC Mode'],             chmap)
            ])
        # return table object 
        return(tab)
    

    def _NiceABCDtableText(self, abcdValueDict: dict[str,int|str|None], channelMap: dict[str,str]) -> str:
        # build nicely formatted text
        text = ''
        for key,val in channelMap.items() : 
            # esclude no-connects from table 
            if(val!='NC') : 
                # <channel label>: <user's input> \n
                text += (str(val) +': ' + str(abcdValueDict[key]) + '\n')
        # cut off the last newline then return string 
        return(text[:-1])
    

    # ------------ VALIDATION ------------


    def _IsOneDeviceValid(self, paramDict: dict) -> bool :
        # check that all params exist 
        if(list(paramDict.keys()).sort() != copy.copy(self._PARAMKEYS).sort() ) :
            raise Exception('[!] Invalid parameters for '+str(self._NAME)+'.')
        # check type of each specific command 
        if( not(
                    isinstance( paramDict[Setup_Interface._PORTKEY],str  ) 
                and isinstance( paramDict['Preamplifier Device'],   str  ) 
                and isinstance( paramDict['Sample Rate'],           int  ) 
                and isinstance( paramDict['Mux Mode'],              bool ) 
                and isinstance( paramDict['Preamplifier Gain'],     dict ) 
                and isinstance( paramDict['Second Stage Gain'],     dict ) 
                and isinstance( paramDict['High-pass'],             dict ) 
                and isinstance( paramDict['Low-pass'],              dict ) 
                and isinstance( paramDict['Bias'],                  dict ) 
                and isinstance( paramDict['DC Mode'],               dict ) 
            )
        ) : 
            raise Exception('[!] Invalid parameter value types for '+str(self._NAME)+'.')
        # check preamp 
        if(not POD_8401HR.IsPreampDeviceSupported(paramDict['Preamplifier Device'])) :
            raise Exception('[!] Preamplifier '+str(paramDict['Preamplifier Device'])+' is not supported for '+str(self._NAME)+'.')
        # check ABCD channel value types
        self._IsChannelTypeValid( paramDict['Preamplifier Gain'],    int   ) 
        self._IsChannelTypeValid( paramDict['Second Stage Gain'],    int   )
        self._IsChannelTypeValid( paramDict['High-pass'],            float )
        self._IsChannelTypeValid( paramDict['Low-pass'],             int   )
        self._IsChannelTypeValid( paramDict['Bias'],                 float )
        self._IsChannelTypeValid( paramDict['DC Mode'],              str   )
        # no exception raised 
        return(True)


    def _IsChannelTypeValid(self, chdict: dict, isType) -> bool :
        # is dict empty?
        if(len(chdict)==0) : 
            raise Exception('[!] Channel dictionary is empty for '+str(self._NAME)+'.')
        # check that keys are ABCD
        if(list(chdict.keys()).sort() != copy.copy(self._CHANNELKEYS).sort() ) :
            raise Exception('[!] Invalid channel keys for '+str(self._NAME)+'.')
        for value in chdict.values() :
            if( value != None and not isinstance(value, isType) ) :
                raise Exception('[!] Invalid channel value type for '+str(self._NAME)+'.')


    # ------------ FILE HANDLING ------------


    def _OpenSaveFile_TXT(self, fname: str) -> IOBase : 
        # open file and write column names 
        f = open(fname, 'w')
        # write time
        f.write( self._GetTimeHeader_forTXT() ) 
        # columns names
        cols = 'Time,'
        devnum = int((fname.split('.')[0]).split('_')[-1]) # get device number from filename
        chmap = POD_8401HR.GetChannelMapForPreampDevice(self._podParametersDict[devnum]['Preamplifier Device'])
        for label in chmap.values() : 
            if(label!='NC') : # exclude no-connects 
                cols += str(label) + ','
        cols += 'Analog EXT0,Analog EXT1,Analog TTL1,Analog TTL2,Analog TTL3,Analog TTL4\n'
        f.write(cols)
        return(f)
    

    def _OpenSaveFile_EDF(self, fname: str, devNum: int) -> EdfWriter :
        # get all channel names for ABCD, excluding no-connects (NC)
        lables = [x for x 
                  in list(POD_8401HR.GetChannelMapForPreampDevice(self._podParametersDict[devNum]['Preamplifier Device']).values()) 
                  if x != 'NC']
        lables.extend(['Analog EXT0','Analog EXT1','Analog TTL1','Analog TTL2','Analog TTL3','Analog TTL4'])
        # number of channels 
        n = len(lables)
        # create file
        f = EdfWriter(fname, n) 
        # get info for each channel
        for i in range(n):
            f.setSignalHeader( i, {
                'label' : lables[i],
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
    def _WriteDataToFile_TXT(file: IOBase, data: list[np.ndarray],  t: np.ndarray) : 
        for i in range(len(t)) : 
            line = [t[i]]
            for arr in data : 
                line.append(arr[i])
            # convert data into comma separated string
            lineToWrite = ','.join(str(x) for x in line) + '\n'
            # write data to file 
            file.write(lineToWrite)


    @staticmethod
    def _WriteDataToFile_EDF(file: EdfWriter, data: list[np.ndarray]) : 
        # write data to EDF file 
        file.writeSamples(data)


    # ------------ STREAM ------------ 


    def _StopStream(self) -> None :
        # tell devices to stop streaming 
        for pod in self._podDevices.values() : 
            pod.WritePacket(cmd='STREAM', payload=0)


    def _StreamThreading(self) -> dict[int,Thread] :
        # create save files for pod devices
        podFiles = {devNum: self._OpenSaveFile(devNum) for devNum in self._podDevices.keys()}
        # make threads for reading 
        readThreads = {
            # create thread to _StreamUntilStop() to dictionary entry devNum
            devNum : Thread(
                    target = self._StreamUntilStop, 
                    args = ( pod, file, params['Sample Rate'], devNum))
            # for each device 
            for devNum,params,pod,file in 
                zip(
                    self._podParametersDict.keys(),     # devNum
                    self._podParametersDict.values(),   # params
                    self._podDevices.values(),          # pod
                    podFiles.values() )                 # file
        }
        for t in readThreads.values() : 
            # start streaming (program will continue until .join() or streaming ends)
            t.start()
        return(readThreads)
    

    def _StreamUntilStop(self, pod: POD_8401HR, file: IOBase|EdfWriter, sampleRate: int, devNum: int) -> None :
        # get file type
        name, extension = os.path.splitext(self._saveFileName)

        # packet to mark stop streaming 
        stopAt = pod.GetPODpacket(cmd='STREAM', payload=0)  
        # start streaming from device  
        startAt = pod.WritePacket(cmd='STREAM', payload=1)

        # initialize times
        t_forEDF: int = 0
        currentTime: float = 0.0 

        # exclude no-connects 
        chmap = POD_8401HR.GetChannelMapForPreampDevice(self._podParametersDict[devNum]['Preamplifier Device'])
        dataColumns = []
        for key,val in chmap.items() : 
            if(val!='NC') : dataColumns.append(key) # ABCD 
        dataColumns.extend(['Analog EXT0','Analog EXT1','Analog TTL1','Analog TTL2','Analog TTL3','Analog TTL4'])


        # start reading
        if(extension == '.edf') : 
            file.writeAnnotation(t_forEDF, -1, "Start")
        while(True):
            # initialize time
            if(extension=='.csv' or extension=='.txt') :
                ti = (round(time.time(),9)) # initial time (sec)

            # initialize data list of arrays 
            data = [np.zeros(sampleRate) for x in dataColumns] 

            # read data for one second
            for i in range(sampleRate):
                # read once 
                r = pod.ReadPODpacket()

                # stop looping when stop stream command is read 
                if(r == stopAt) : 
                    if(extension=='.edf') : 
                        file.writeAnnotation(t_forEDF, -1, "Stop")
                    file.close()
                    return  ##### END #####
                # skip if start stream command is read 
                elif(r == startAt) :
                    i = i-1
                    continue

                # interpret packet
                rt = pod.TranslatePODpacket(r)
                for d,ch in zip(data, dataColumns) : 
                    d[i] = self._uV(rt[ch])

            if(extension=='.csv' or extension=='.txt') :
                # get average sample period
                tf = round(time.time(),9) # final time
                td = tf - ti # time difference 
                average_td = (round((td/sampleRate), 9)) # time between samples 

                # increment time for each sample
                times = np.zeros(sampleRate)
                for i in range(sampleRate):
                    times[i] = (round(currentTime, 9))
                    currentTime += average_td  #adding avg time differences + CurrentTime = CurrentTime

                # write to file 
                self._WriteDataToFile_TXT(file, data, times)

            elif(extension=='.edf') :              
                self._WriteDataToFile_EDF(file, data)
                t_forEDF += 1
        # end while 


    ########################################
    #               WORKING
    ########################################



    