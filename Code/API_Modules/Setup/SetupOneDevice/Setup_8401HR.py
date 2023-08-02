

# enviornment imports
import os 
import time 
import numpy        as     np
from   texttable    import Texttable
from   threading    import Thread
from   io           import IOBase
from   pyedflib     import EdfWriter

# local imports
from Setup.SetupOneDevice   import Setup_Interface
from Setup.Inputs           import UserInput
from Packets                import Packet_Standard, Packet_Binary5
from Devices                import POD_8401HR
from Parameters             import Params_8401HR

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Setup_8401HR(Setup_Interface) : 
    """
    Setup_8401HR provides the setup functions for an 8206-HR POD device. \
    REQUIRES FIRMWARE 1.0.2 OR HIGHER.
    """
    # ============ GLOBAL CONSTANTS ============      ========================================================================================================================
    

    _PHYSICAL_BOUND_uV : int = 2046 
    """Class-level integer representing the max/-min physical value in uV. Used for \
    EDF files. 
    """

    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self) -> None:
        super().__init__()
        self._podParametersDict : dict[int,Params_8401HR] = {}  


    # ============ PUBLIC METHODS ============      ========================================================================================================================


    @staticmethod
    def GetDeviceName() -> str : 
        """returns the name of the 8401-HR POD device.

        Returns:
            str: 8401-HR.
        """
        # returns the name of the POD device 
        return('8401-HR')
    

    # ============ PRIVATE METHODS ============      ========================================================================================================================


    # ------------ DEVICE CONNECTION ------------


    def _ConnectPODdevice(self, deviceNum: int, deviceParams: Params_8401HR) -> bool : 
        """Creates a POD_8206HR object and write the setup parameters to it. 

        Args:
            deviceNum (int): Integer of the device's number.
            deviceParams (Params_8401HR): Device parameters.

        Returns:
            bool: True if connection was successful, false otherwise.
        """
        success = False 
        try : 
            # get port name 
            port = deviceParams.port.split(' ')[0] # isolate COM# from rest of string
            # create POD device 
            pod = POD_8401HR(
                port        = port, 
                ssGain      = deviceParams.ssGain,
                preampGain  = deviceParams.preampGain,
            )
            # test if connection is successful
            if(not self._TestDeviceConnection(pod)): raise Exception('Could not connect to POD device.')
            # write devicesetup parameters
            pod.WriteRead('SET SAMPLE RATE', deviceParams.sampleRate)
            pod.WriteRead('SET MUX MODE', int(deviceParams.muxMode)) # bool to int 
            # write channel specific setup parameters
            for channel in range(4) : 
                if(deviceParams.highPass[channel] != None) : pod.WriteRead('SET HIGHPASS', (channel, self._CodeHighpass(deviceParams.highPass[channel])))
                if(deviceParams.lowPass [channel] != None) : pod.WriteRead('SET LOWPASS',  (channel, deviceParams.lowPass[channel]))
                if(deviceParams.bias    [channel] != None) : pod.WriteRead('SET BIAS',     (channel, POD_8401HR.CalculateBiasDAC_GetDACValue(deviceParams.bias[channel])))
                if(deviceParams.dcMode  [channel] != None) : pod.WriteRead('SET DC MODE',  (channel, self._CodeDCmode(deviceParams.dcMode[channel])))
                if(deviceParams.ssGain  [channel] != None and
                    deviceParams.highPass[channel] != None) : pod.WriteRead('SET SS CONFIG', (channel, POD_8401HR.GetSSConfigBitmask(gain=deviceParams.ssGain[channel], highpass=deviceParams.highPass[channel])))
            # successful write if no exceptions raised 
            self._podDevices[deviceNum] = pod
            success = True
            print('Successfully connected device #'+str(deviceNum)+' to '+port+'.')
        except Exception as e :
            self._podDevices[deviceNum] = False # fill entry with bad value
            print('[!] Failed to connect device #'+str(deviceNum)+' to '+port+': '+str(e))
        # return True when connection successful, false otherwise
        return(success)
    

    @staticmethod
    def _CodeHighpass(highpass: float) -> int : 
        """Gets the integer payload to use for 'SET HIGHPASS' given a highpass value.

        Args:
            highpass (float): Highpass value in Hz.

        Raises:
            Exception: High-pass value is not supported.

        Returns:
            int: Integer code representing the highpass value.
        """
        match highpass : 
            case  0.5  : return(0)
            case  1.0  : return(1)
            case 10.0  : return(2)
            case  0.0  : return(3)
            case _ : raise Exception('[!] High-pass of '+str(highpass)+' Hz is not supported.')


    @staticmethod
    def _CodeDCmode(dcMode: str) -> int : 
        """gets the integer payload to use for 'SET DC MODE' commands given the mode.

        Args:
            dcMode (str): DC mode VBIAS or AGND.

        Raises:
            Exception: DC Mode value is not supported.

        Returns:
            int: Integer code representing the DC mode.
        """
        match dcMode : 
            case 'VBIAS' : return(0)
            case 'AGND'  : return(1)
            case _ : raise Exception('[!] DC Mode \''+str(dcMode)+'\' is not supported.')


    # ------------ SETUP POD PARAMETERS ------------


    def _GetParam_onePODdevice(self, forbiddenNames: list[str] = []) -> Params_8401HR :
        """Asks the user to input all the device parameters. 

        Args:
            forbiddenNames (list[str]): List of port names already used by other devices.

        Returns:
            Params_8401HR: Device parameters.
        """
        # ask for port first
        port = self._ChoosePort(forbiddenNames)
        # get channel map for the user's preamplifier 
        preampDevice = self._GetPreampDeviceName()
        chmap = POD_8401HR.GetChannelMapForPreampDevice(preampDevice)
        # get all parameters 
        params = Params_8401HR(
            # get parameters for full device 
            port         = port,
            preampDevice = preampDevice,
            sampleRate   = UserInput.AskForIntInRange('Set sample rate (Hz)', 2000, 20000),
            muxMode      = UserInput.AskYN('Use mux mode?'),
            # get parameters for each ABCD channel
            preampGain   = self._SetForMappedChannels('Set preamplifier gain (1, 10, or 100) for...',        chmap, self._SetPreampGain  ),
            ssGain       = self._SetForMappedChannels('Set second stage gain (1 or 5) for...',               chmap, self._SetSSGain      ),
            highPass     = self._SetForMappedChannels('Set high-pass filter (0, 0.5, 1, or 10 Hz) for...',   chmap, self._SetHighpass    ),
            lowPass      = self._SetForMappedChannels('Set low-pass filter (21-15000 Hz) for...',            chmap, self._SetLowpass     ),
            bias         = self._SetForMappedChannels('Set bias (+/- 2.048 V) for...',                       chmap, self._SetBias        ),
            dcMode       = self._SetForMappedChannels('Set DC mode (VBIAS or AGND) for...',                  chmap, self._SetDCMode      ) 
        )
        return(params)


    def _GetPreampDeviceName(self) -> str : 
        """Asks the user to select a mouse/rat preamplifier.

        Returns:
            str: String of the chosen preamplifier.
        """
        deviceList = POD_8401HR.GetSupportedPreampDevices()
        print('Available preamplifiers: '+', '.join(deviceList))
        return( UserInput.AskForStrInList(
            prompt='Set mouse/rat preamplifier',
            goodInputs=deviceList,
            badInputMessage='[!] Please input a valid mouse/rat preamplifier.'))

        
    # func MUST take one argument, which is the channel map value 
    def _SetForMappedChannels(self, message: str, channelMap: dict[str,str], func: 'function') -> tuple[int|None] : 
        """Asks the user to input values for all channels (excluding no-connects). 

        Args:
            message (str): Message to ask the user.
            channelMap (dict[str,str]): Maps the ABCD channels to the sensor's channel name. 
            func (function): a function that asks the user for an input. takes one string \
                parameter and returns one value.  

        Returns:
            tuple[int|None] : Tuple with user inputs for values for the ABCD channels
        """
        print(message)
        channels = [None] * 4
        for i, label in enumerate(channelMap.values()): 
            # ask for value if not No-Connect (NC)
            if(label != 'NC') : 
               channels[i] = func(label)
        return(tuple(channels))
    

    @staticmethod
    def _SetPreampGain(channelName: str) -> int|None : 
        """Asks the user for the preamplifier gain.

        Args:
            channelName (str): Name of the channel.

        Returns:
            int|None: An integer for the gain, or None if no gain.
        """
        gain = UserInput.AskForIntInList(
            prompt='\t'+str(channelName), 
            goodInputs=[1,10,100], 
            badInputMessage='[!] For EEG/EMG, the gain must be 10 or 100. For biosensors, the gain is 1 (None).')
        if(gain == 1) : 
            return(None)
        return(gain)
        

    @staticmethod
    def _SetSSGain(channelName: str) -> int : 
        """Asks the user for the second stage gain.

        Args:
            channelName (str): Name of the channel.

        Returns:
            int: An integer for the gain.
        """
        return( UserInput.AskForIntInList(
            prompt='\t'+str(channelName), 
            goodInputs=[1,5], 
            badInputMessage='[!] The gain must be 1 or 5.') )


    @staticmethod
    def _SetHighpass(channelName: str) -> float|None : 
        """Asks the user for the high-pass in Hz (0.5,1,10Hz, or DC).

        Args:
            channelName (str): Name of the channel.

        Returns:
            float|None: A float for the high-pass frequency in Hz, or None if DC.
        """
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
        """Asks the user for the low-pass in Hz (21-15000Hz).

        Args:
            channelName (str): Name of the channel.

        Returns:
            int|None: An integer for the low-pass frequency in Hz.
        """
        return(UserInput.AskForIntInRange(
            prompt='\t'+str(channelName), 
            minimum=21, maximum=15000, 
            thisIs='The low-pass filter', unit=' Hz' ))
    
    
    @staticmethod
    def _SetBias(channelName: str) -> float : 
        """Asks the user for the bias voltage in V (+/-2.048V).

        Args:
            channelName (str): Name of the channel.

        Returns:
            float: A float for thebias voltage in V.
        """
        return( UserInput.AskForFloatInRange(
            prompt='\t'+str(channelName),
            minimum=-2.048,
            maximum=2.048,
            thisIs='The bias', unit=' V (default is 0.6 V)'
        ))
    

    @staticmethod
    def _SetDCMode(channelName: str) -> str : 
        """Asks the user for the DC mode (VBIAS or AGND).

        Args:
            channelName (str): Name of the channel.

        Returns:
            str: String for the DC mode.
        """
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
        """Builds a table containing the parameters for all POD devices.

        Returns:
            Texttable: Texttable containing all parameters.
        """
        # setup table 
        tab = Texttable(160)
        # write column names
        tab.header(['Device #','Port','Preamplifier Device',
                    'Sample Rate (Hz)','Mux Mode', 'Preamplifier Gain','Second Stage Gain',
                    'High-pass (Hz)','Low-pass (Hz)','Bias (V)','DC Mode'])
        # for each device 
        for key,val in self._podParametersDict.items() :
            # get channel mapping for device 
            chmap = POD_8401HR.GetChannelMapForPreampDevice(val.preampDevice)
            # write row to table 
            tab.add_row([
                key, val.port, val.preampDevice, val.sampleRate,str(val.muxMode),
                self._NiceABCDtableText(val.preampGain, chmap),
                self._NiceABCDtableText(val.ssGain,     chmap),
                self._NiceABCDtableText(val.highPass,   chmap),
                self._NiceABCDtableText(val.lowPass,    chmap),
                self._NiceABCDtableText(val.bias,       chmap),
                self._NiceABCDtableText(val.dcMode,     chmap)
            ])
        # return table object 
        return(tab)
    

    def _NiceABCDtableText(self, abcdValues: list[int|str|None], channelMap: dict[str,str]) -> str:
        """Builds a string that formats the channel values to be input into the parameter table.

        Args:
            abcdValueDict (dict[str,int | str | None]): Dictionary with ABCD keys.
            channelMap (dict[str,str]): Maps the ABCD channels to the sensor's channel name. 

        Returns:
            str: String with "channel name: value newline..." for each channel.
        """
        # build nicely formatted text
        text = ''
        for i,val in enumerate(channelMap.values()) : 
            # esclude no-connects from table 
            if(val!='NC') : 
                # <channel label>: <user's input> \n
                text += (str(val) +': ' + str(abcdValues[i]) + '\n')
        # cut off the last newline then return string 
        return(text[:-1])
    

    # ------------ FILE HANDLING ------------


    def _OpenSaveFile_TXT(self, fname: str) -> IOBase : 
        """Opens a text file and writes the column names. Writes the current date/time at \
        the top of the txt file.

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
        cols = 'Time,'
        devnum = int((fname.split('.')[0]).split('_')[-1]) # get device number from filename
        chmap = POD_8401HR.GetChannelMapForPreampDevice(self._podParametersDict[devnum].preampDevice)
        for label in chmap.values() : 
            if(label!='NC') : # exclude no-connects 
                cols += str(label) + ','
        cols += 'Analog EXT0,Analog EXT1,Analog TTL1,Analog TTL2,Analog TTL3,Analog TTL4\n'
        f.write(cols)
        return(f)
    

    def _OpenSaveFile_EDF(self, fname: str, devNum: int) -> EdfWriter :
        """Opens EDF file and write header.

        Args:
            fname (str): String filename.
            devNum (int): Integer device number.

        Returns:
            EdfWriter: Opened file.
        """
        # get all channel names for ABCD, excluding no-connects (NC)
        lables = [x for x 
                  in list(POD_8401HR.GetChannelMapForPreampDevice(self._podParametersDict[devNum].preampDevice).values()) 
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
                'sample_rate' : self._podParametersDict[devNum].sampleRate,
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
        """Writes data to an open text file.

        Args:
            file (IOBase): opened write file.
            data (list[np.ndarray]): List with one item for each channel.
            t (np.ndarray): list with the time stamps (in seconds).
        """
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
        """Writes data to an open EDF file.

        Args:
            file (EdfWriter): opened EDF file.
            data (list[np.ndarray]): List with one item for each channel.
        """
        # write data to EDF file 
        file.writeSamples(data)


    # ------------ STREAM ------------ 


    def StopStream(self) -> None :
        """Write a command to stop streaming data to all POD devices."""
        # tell devices to stop streaming 
        for pod in self._podDevices.values() : 
            pod.WritePacket(cmd='STREAM', payload=0)


    def _StreamThreading(self) -> dict[int,Thread] :
        """Opens a save file, then creates a thread for each device to stream and write \
        data from. 

        Returns:
            dict[int,Thread]: Dictionary with keys as the device number and values as \
                the started Thread.
        """
        # create save files for pod devices
        podFiles = {devNum: self._OpenSaveFile(devNum) for devNum in self._podDevices.keys()}
        # make threads for reading 
        readThreads = {
            # create thread to _StreamUntilStop() to dictionary entry devNum
            devNum : Thread(
                    target = self._StreamUntilStop, 
                    args = ( pod, file, params.sampleRate, devNum))
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
        """Streams data from a POD device and saves data to file. Stops looking when a stop \
        stream command is read. Calculates average time difference across multiple packets to \
        collect a continuous time series data. 

        Args:
            pod (POD_8206HR): POD device to read from.
            file (IOBase | EdfWriter): open file.
            sampleRate (int): Integer sample rate in Hz.
        """
        # get file type
        name, extension = os.path.splitext(self._saveFileName)

        # packet to mark stop streaming 
        stopAt = pod.GetPODpacket(cmd='STREAM', payload=0)  
        # start streaming from device  
        pod.WritePacket(cmd='STREAM', payload=1)

        # initialize times
        t_forEDF: int = 0
        currentTime: float = 0.0 

        # exclude no-connects 
        chmap = POD_8401HR.GetChannelMapForPreampDevice(self._podParametersDict[devNum].preampDevice)
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
                r: Packet_Standard|Packet_Binary5 = pod.ReadPODpacket()

                # stop looping when stop stream command is read 
                if(r.rawPacket == stopAt) : 
                    if(extension=='.edf') : 
                        file.writeAnnotation(t_forEDF, -1, "Stop")
                    file.close()
                    return  ##### END #####

                if(isinstance(r, Packet_Binary5)) : 
                    # interpret Packet_Binary5 packet
                    rt: dict = r.TranslateAll()
                    for d,ch in zip(data, dataColumns) : 
                        d[i] = self._uV(rt[ch])
                else : 
                    # skip standard stream info packets
                    i = i-1
                    continue

            if(extension=='.csv' or extension=='.txt') :
                # get average sample period
                tf = round(time.time(),9) # final time
                td = tf - ti # time difference 
                average_td = (round((td/sampleRate), 9)) # time between samples 
                # increment time for each sample
                times = np.zeros(sampleRate)
                for i in range(sampleRate):
                    times[i] = (round(currentTime, 9))
                    currentTime += average_td  # adding avg time differences + CurrentTime = CurrentTime
                # write to file 
                self._WriteDataToFile_TXT(file, data, times)

            elif(extension=='.edf') :           
                self._WriteDataToFile_EDF(file, data)
                t_forEDF += 1
        # end while 