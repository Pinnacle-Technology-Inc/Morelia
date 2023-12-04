# enviornment imports
from texttable   import Texttable
from io          import IOBase
from threading   import Thread
import time

# local imports
from Setup.SetupOneDevice   import SetupInterface
from Setup.Inputs           import UserInput
from PodApi.Packets         import PacketStandard
from PodApi.Devices         import Pod8274D
from PodApi.Parameters      import Params8274D

# authorship
__author__      = "Sree Kondi"
__maintainer__  = "Sree Kondi"
__credits__     = ["Sree Kondi", "Thresa Kelly" "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Setup8274D(SetupInterface) : 
    """
    Setup_8480SC provides the setup functions for an 8480-SC POD device. 
    
    Attributes:
        _streamMode (bool): Set to True when the user wants to start streaming data from \
            an 8480 POD device, False otherwise.
    """

    # ============ DUNDER METHODS ============      ========================================================================================================================
    
    
    def __init__(self) -> None :
        super().__init__()
        self._podParametersDict : dict[int,Params8274D] = {} 
        self._streamMode : bool = False


    # ============ PUBLIC METHODS ============      ========================================================================================================================
    
    
    @staticmethod
    def GetDeviceName() -> str : 
        """Returns the name of the POD device.

        Returns:
            str: String of _NAME.
        """
        print("8")
        return('8274D')
    

    @staticmethod
    def GetSupportedFileExtensions() -> list[str] : 
        """Returns a list containing valid file extensions. 

        Returns:
            list[str]: List of string file extensions.
        """
        return(['.txt','.csv'])


    def StopStream(self) -> None: 
        """Update the state flag to signal to stop streaming data.
        """
        self._streamMode = False
    
     
    # ============ PRIVATE METHODS ============      ========================================================================================================================
    
    
    # ------------ DEVICE CONNECTION ------------


    def _ConnectPODdevice(self, deviceNum: int, deviceParams: Params8274D) -> bool :  
        """Creates a POD_8206HR object and write the setup parameters to it. 

        Args:
            deviceNum (int): Integer of the device's number.
            deviceParams (Params_8274D): Device parameters.

        Returns:
            bool: True if connection was successful, false otherwise.
        """
        print("11")
        success = False 
        # get port name 
        port = deviceParams.port.split(' ')[0] # isolate COM# from rest of string
        
        try : 
            # create POD device 
            pod = Pod8274D(port=port)
            # test if connection is successful
            if(not self._TestDeviceConnection(pod)): raise Exception('Could not connect to POD device.')
            # write setup parameters
            address = pod.WriteRead('LOCAL SCAN', deviceParams.localScan)
            #print("address", address)
            pod.WriteRead('CONNECT BY ADDRESS', (address), deviceParams.connectAdd)
            pod.WriteRead('SET SAMPLE RATE', deviceParams.sampleRate)
            pod.WriteRead('GET NAME', deviceParams.name)
            pod.WriteRead('DISCONNECT ALL', deviceParams.disconnect)
            ####testing
            address = pod.WriteRead('LOCAL SCAN', deviceParams.localScan)
            #print("address", address)
            pod.WriteRead('CONNECT BY ADDRESS', (address), deviceParams.connectAdd)
            pod.WriteRead('SET SAMPLE RATE', deviceParams.sampleRate)
            #pod.WriteRead('SET PERIOD', deviceParams.period)
            ###testing
            #pod.WriteRead('SET STIMULUS', deviceParams.sampleRate)
            #pod.WriteRead('GET MODEL NUMBER') #dont' think it needs a input
            #pod.WriteRead('CONNECT', 1, deviceParams.connect)
            # successful write if no exceptions raised 
            self._podDevices[deviceNum] = pod
            success = True
            print('Successfully connected device #'+str(deviceNum)+' to '+port+'.')
        except Exception as e :
            self._podDevices[deviceNum] = False # fill entry with bad value
            print('[!] Failed to connect device #'+str(deviceNum)+' to '+port+': '+str(e))
        # return True when connection successful, false otherwise
        return(success)

    def _GetParam_onePODdevice(self, forbiddenNames: list[str] = []) -> Params8274D : 
        """Asks the user to input all the device parameters. 

        Args:
            forbiddenNames (list[str]): List of port names already used by other devices.

        Returns:
            Params_8480SC: Device parameters.
        """
        # ask for port first
        return(Params8274D(
            port              =     self._ChoosePort(forbiddenNames),
            localScan         =     UserInput.AskForIntInRange('\nSet Local Scan', 0, 1),
            #deviceList         =     UserInput.AskForIntInRange('\nSet a device Slot', 0, 1),
            sampleRate        =     UserInput.AskForIntInList('\nSet Sample Rate (0,1,2,3)', [0,1,2,3]),
            period            =     UserInput.AskForInput('\nSet Period ')
            #stimulus          =     UserInput. 
        ))
        
    def _GetPODdeviceParameterTable(self) -> Texttable :
        """Builds a table containing the parameters for all POD devices.

        Returns:
            Texttable: Texttable containing all parameters.
        """
        # setup table 
        tab = Texttable(160)
        # write column names
        tab.header(['Device #','Port','Local Scan', 'Sample Rate', 'Period'])
        # write rows
        for key,val in self._podParametersDict.items() :
            localScan_str = f" Local Scan: {val.localScan}\n  "
            sampleRate_str = f" Sample Rate: {val.sampleRate}\n  "
            period_str = f" Period: {val.period}\n  "
            tab.add_row([key, val.port, localScan_str, sampleRate_str, period_str])
        return(tab)
    

    def _OpenSaveFile_EDF(self, fname: str, devNum: int) :
        """EDF files are not supported for 8480 POD devices. Overwrites the \
        parent's method, which would open an EDF file and write the header.

        Args:
            fname (str): String filename. Not used.
            devNum (int): Integer device number. Not used.

        Raises:
            Exception: EDF filetype is not supported for 8480 POD devices.
        """
        raise Exception('[!] POD Device 8480-SC does not support EDF filetype.')
    

    def _OpenSaveFile_TXT(self, fname: str) -> IOBase : 
        """Opens a text file and writes the column names. Writes the current date/time \
            at the top of the txt file.

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
        f.write('\nTime (s),Command Number,Payload\n')
        return(f)

    def StopStream(self) -> None: 
        """Update the state flag to signal to stop streaming data.
        """
        self._streamMode = False


    def _StreamThreading(self) -> dict[int,Thread] :
        """Opens a save file, then creates a thread for each device to stream and write \
        data from. 

        Returns:
            dict[int,Thread]: Dictionary with keys as the device number and values as the \
                started Thread.
        """
        print("###")
        # set state 
        self._streamMode = True
        # create save files for pod devices
        podFiles = {devNum: self._OpenSaveFile(f"file_{devNum}.txt") for devNum in self._podDevices.keys()}
        # make threads for reading 
        readThreads = {
            # create thread to _StreamUntilStop() to dictionary entry devNum
            devNum : Thread(
                    target = self._StreamUntilStop, 
                    args   = (pod, file))
            # for each device 
            for devNum,pod,file in 
                zip(
                    self._podParametersDict.keys(),     # devNum
                    self._podDevices.values(),          # pod
                    podFiles.values() )                 # file
        }
        for t in readThreads.values() : 
            # start streaming (program will continue until .join() or streaming ends)
            t.start()
        return(readThreads)
        

    def _StreamUntilStop(self, pod: Pod8274D, file: IOBase) -> None :
        """Saves a log of all packets recieved from the 8480 POD device until the user decides \
        to stop streaming.

        Args:
            pod (POD_8480): POD device to read from. 
            file (IOBase): Opened text file to save data to.
        """
        # initialize
        currentTime : float = 0.0
        t : float = (round(time.time(),9)) # initial time (sec)          
        print("!!!")
        # start waiting for data   
        while(self._streamMode) : 
            try : 
                # attempt to read packet.         
                read: PacketStandard = pod.ReadPODpacket(timeout_sec=1)
                # update time by adding (dt = tf - ti)
                currentTime += (round(time.time(),9)) - t 
                # build line to write 
                data = [str(currentTime), str(read.CommandNumber())]
                if(read.HasPayload()) : data.append(str(read.Payload()))
                else :                  data.append('None')
                # write to file
                file.write(','.join(data) + '\n')
                # update initial time for next loop 
                t = (round(time.time(),9)) # initial time (sec) 
            except : 
                continue # keep looping 
            # end while 
        # streaming done
        file.close()

    