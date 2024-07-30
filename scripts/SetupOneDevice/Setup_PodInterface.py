# enviornment imports
import os
import time
from   texttable  import Texttable
from   pyedflib   import EdfWriter
from   threading  import Thread
from   io         import IOBase
from   datetime   import datetime

# local imports
from Setup.Inputs       import UserInput
from Morelia.Packets    import Packet, PacketStandard
from Morelia.Devices    import Pod
from Morelia.Parameters import Params

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class SetupInterface : 
    """
    Setup_Interface provides the basic interface of required methods for subclasses to implement. \
    SetupPodDevices.py is designed to handle any of these children.

    Attributes:
        _podDevices (dict[int,POD_Basics]): Instance-level dictionary of pod device objects. MUST have \
            keys as device number.
        _podParametersDict (dict[int,Params_Interface]): Instance-level dictionary of device information. \ 
            MUST have keys as device number.
        _saveFileName (str): Instance-level string filename: <path>/file.ext. The device name and number \
            will be appended to the filename.
    """

    # ============ REQUIRED INTERFACE METHODS ============      ========================================================================================================================


    @staticmethod
    def GetDeviceName() -> str : 
        """returns the name of the POD device.

        Returns:
            str: GENERIC.
        """
        # NOTE replace GENERIC with the correct child class' name 
        return('GENERIC')   
    
    
    @staticmethod
    def GetSupportedFileExtensions() -> list[str] : 
        """Returns a list containing valid file extensions. 

        Returns:
            list[str]: List of string file extensions.
        """
        # NOTE add or remove extensions in child class if needed
        return(['.csv','.txt','.edf'])


    def _GetParam_onePODdevice(self, forbiddenNames: list[str] = []) -> Params :
        """Asks the user to input all the device parameters. 

        Args:
            forbiddenNames (list[str]): List of port names already used by other devices. Defaults to [].

        Returns:
            Params_Interface: Device parameters.
        """
        pass


    def _ConnectPODdevice(self, deviceNum: int, deviceParams: Params) -> bool : 
        """Creates a POD device object and write the setup parameters to it. 

        Args:
            deviceNum (int): Integer of the device's number.
            deviceParams (Params_Interface): Device parameters.

        Returns:
            bool: True if connection was successful, false otherwise.
        """
        # write setup commands to initialize the POD device with the user's parameters
        pass

    def _GetPODdeviceParameterTable(self) -> Texttable : 
        """Builds a table containing the parameters for all POD devices.

        Returns:
            Texttable: Table containing all parameters.
        """
        pass


    def _OpenSaveFile_TXT(self, fname: str) -> IOBase : 
        """Opens a text file and writes the column names. Writes the current date/time at the top of \
        the txt file.

        Args:
            fname (str): String filename.

        Returns:
            IOBase: Opened file.
        """
        # open a text file and write column names 
        pass


    def _OpenSaveFile_EDF(self, fname: str, devNum: int) -> EdfWriter :
        """Opens EDF file and write header.

        Args:
            fname (str): String filename.
            devNum (int): Integer device number.

        Returns:
            EdfWriter: Opened file.
        """
        # create an EDF file and write all channel information
        pass


    def StopStream(self) -> None: 
        """Write a command to stop streaming data to all POD devices."""
        pass
    

    def _StreamThreading(self) -> tuple[dict[int,Thread]] | dict[int,Thread] :
        """Start streaming from each POD device and save each to a file. 

        Returns:
            tuple[dict[int,Thread]] | dict[int,Thread]: Dictionary with keys as the device number and \
                values as the started Thread. If a tuple, the first item is the Bucket and second is the \
                BucketDrain Threads. 
        """
        # each POD device has its own thread 
        pass


    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self) -> None :
        """Initializes the class instance variables."""
        self._podDevices : dict[int,Pod]  = {}  # dict of pod device objects. MUST have keys as the device number
        self._podParametersDict : dict[int,Params] = {} # dictionary of device information. MUST have keys as the device number
        self._saveFileName : str = ''   # string filename: <path>/file.ext # the device name and number will be appended to the filename 


    def __del__(self) -> None :
        """Disconnects all POD devices."""
        # delete all POD objects 
        self._DisconnectAllPODdevices


    # ============ PUBLIC/PRIVATE METHODS ============      ========================================================================================================================


    # ------------ VALIDATION ------------
    

    def AreDeviceParamsValid(self, paramDict: None|dict[int,Params]) :
        """Checks if the parameters dictionary is valid. 

        Args:
            paramDict (None | dict[int,Params_Interface]): Dictionary of parameters for all POD devices. 

        Raises:
            Exception: Parameters must be contained in a dictionary.
            Exception: Device keys must be integer type.
            Exception: Device parameters must be dictionary type.
            Exception: Device parameters dictionary is empty.
        """
        if(paramDict == None) : 
            return(True)
        # is params a dict?
        if(not isinstance(paramDict, dict)) :
            raise Exception('[!] Parameters must be contained in a dictionary.')
        # are keys int and value dict
        for key,value in paramDict.items() : 
            if(not isinstance(key,int)) : 
                raise Exception('[!] Device keys must be integer type for '+str(self.GetDeviceName())+'.')
            if(not isinstance(value,Params)) : 
                raise Exception('[!] Device parameters must be Params_Interface type for '+str(self.GetDeviceName())+'.')
        # no exceptions raised
        return(True)
    

    # ------------ DEVICE CONNECTION ------------


    @staticmethod
    def _SetNumberOfDevices(name: str) -> int : 
        """Asks the user for how many devices they want to setup.

        Args:
            name (str): Name of the POD device type.

        Returns:
            int: Integer number of POD devices desired by the user. 
        """
        try : 
            # request user imput
            n = int(input('\nHow many '+str(name)+' devices do you want to use?: '))
            # number must be positive
            if(n<=0):
                print('[!] Number must be greater than zero.')
                return(SetupInterface._SetNumberOfDevices(name))
            # return number of POD devices 
            return(n)
        except : 
            # print error and start over
            print('[!] Please enter an integer number.')
            return(SetupInterface._SetNumberOfDevices(name))
        

    def ConnectAllPODdevices(self) -> bool : 
        """Connects all setup POD devices.

        Returns:
            bool: True if all devices are successfully connected, false otherwise.
        """
        # delete existing 
        self._DisconnectAllPODdevices()
        # connect new devices
        print('\nConnecting '+self.GetDeviceName()+' devices...')
        # setup each POD device
        areAllGood = True
        for key,val in self._podParametersDict.items():
           # areAllGood is false if any device fails
           areAllGood = areAllGood and self._ConnectPODdevice(key,val)
        return(areAllGood)


    def _DisconnectAllPODdevices(self) -> None :
        """Disconnects all POD devices by deleted all POD obejcts."""
        for k in list(self._podDevices.keys()) : 
            pod = self._podDevices.pop(k)
            del pod # port closed on delete in COM_io


    def AddPODdevice(self) -> None :
        """Asks the user for the parameters for the new device. A new device number \
        is generated.
        """
        nextNum = max(self._podParametersDict.keys())+1
        self._PrintDeviceNumber(nextNum)
        self._podParametersDict[nextNum] = self._GetParam_onePODdevice(self._GetForbiddenNames())


    # ------------ SETUP POD PARAMETERS ------------

    
    def SetupPODparameters(self, podParametersDict:dict[int,Params]|None=None) -> None :
        """Sets the parameters for the POD devices.

        Args:
            podParametersDict (dict[int,Params_Interface] | None, optional): dictionary of the device parameters \
                for all devices. Defaults to None.
        """
        # get dictionary of POD device parameters
        if(podParametersDict==None):
            # get setup parameters for all POD devices
            self._podParametersDict = self._GetParam_allPODdevices()  
            # display parameters and allow user to edit them
            self.ValidateParams()          
        else:
            self._podParametersDict = podParametersDict
        # connect and initialize all POD devices
        self.ConnectAllPODdevices()


    def _GetParam_allPODdevices(self) -> dict[int,Params] :
        """First gets the number of POD devices, then asks the user for the information \
        for each device.

        Returns:
            dict[int,Params_Interface]: Dictionary with device numbers for keys and parameters for values.
        """
        # get the number of devices 
        numDevices = self._SetNumberOfDevices(self.GetDeviceName())
        # initialize 
        portNames = [None] * numDevices
        podDict = {}
        # get information for each POD device 
        for i in range(numDevices) : 
            # current index 
            self._PrintDeviceNumber(i+1)
            # get parameters
            onePodDict = self._GetParam_onePODdevice(portNames)
            # update lists 
            portNames[i] = onePodDict.port
            podDict[i+1] = onePodDict
        # save dict containing information to setup all POD devices
        return(podDict)

    @staticmethod
    def _ChoosePort(forbidden:list[str]=[]) -> str : 
        """Systems checks user's Operating System, and chooses ports accordingly.

        Args:
            forbidden (list[str], optional): List of port names that are already used. Defaults to [].

        Returns:
            str: String name of the port.
        """
        return Pod.ChoosePort(forbidden)
    
    # ------------ EDIT POD PARAMETERS ------------


    def ValidateParams(self) -> None : 
        """Displays a table of the parameters of all devices, then asks the user if everything \
        is correct. The user can then edit the parameters of a device. 
        """
        # display all pod devices and parameters
        self.DisplayPODdeviceParameters()
        # ask if params are good or not
        validParams = UserInput.AskYN(question='Are the '+self.GetDeviceName()+' device parameters correct?')
        # edit if the parameters are not correct 
        if(not validParams) : 
            self._EditParams()
            self.ValidateParams()


    def _RemoveDevice(self) -> None : 
        """Asks the user for a device number to remove, then deletes that device. This will \
        only remove a device if there are more than one options. 
        """
        # check that there is a device to delete
        if(len(self._podParametersDict) <= 1 ) : 
            print('[!] Cannot remove the last device.')
            return
        # chose device # to remove 
        removeThis = self._SelectDeviceFromDict('Remove')
        # remove from dicts
        self._podParametersDict.pop(removeThis)
        self._podDevices.pop(removeThis)
        # print feedback
        print('Device #'+str(removeThis)+' removed.')


    def _EditParams(self) -> None :
        """Asks the user which device to edit, and then asks them to re-input the device parameters."""
        # chose device # to edit
        editThis = self._SelectDeviceFromDict('Edit')
        # get all port names except for device# to be edited
        forbiddenNames = self._GetForbiddenNames(exclude=self._podParametersDict[editThis].port)
        # edit device
        self._PrintDeviceNumber(editThis)
        self._podParametersDict[editThis] = self._GetParam_onePODdevice(forbiddenNames)


    def _SelectDeviceFromDict(self, action: str) -> int :
        """Asks the user to select a valid device number. The input must be an integer number \
        of an existing device. 

        Args:
            action (str): Description of the action to be performed on the device.

        Returns:
            int: Integer for the device number.
        """
        podKey = UserInput.AskForInt(str(action)+' '+self.GetDeviceName()+' device #')
        # check is pod device exists
        keys = self._podParametersDict.keys()
        if(podKey not in keys) : 
            print('[!] Invalid device number. Please try again.')
            return(self._SelectDeviceFromDict(action))
        else:
            # return the pod device number
            return(podKey)
        

    def _GetForbiddenNames(self, exclude:str|None=None) -> list[str] :
        """Generates a list of port names used by the active pod devices. There is an option to \
        exclude an additional name from the list.

        Args:
            exclude (str | None, optional): String port name to exclude from the returned list. \
                Defaults to None.

        Returns:
            list[str]: List of string names of ports in use.
        """
        if(exclude == None) : 
            # get port name for each POD device 
            portNames = [x.port for x in self._podParametersDict.values()]
        else :
            portNames = [x.port for x in self._podParametersDict.values() if exclude != x.port]
        return(portNames)
    

    # ------------ DISPLAY POD PARAMETERS ------------


    def GetPODparametersInit(self) -> str :
        """Gets a dictionary whose keys are the device number and the value is the device parameters dict.
        Returns:
            str: String representation of a dictionary of POD device parameters. The keys are the device number.
        """
        initParams = '{'
        for key,val in self._podParametersDict.items() :
            initParams += ' '+str(key)+' : '+val.GetInit()+','
        initParams = initParams[:-1] + ' }' # cut off last comma and add close bracket 
        return(initParams)


    @staticmethod
    def _PrintDeviceNumber(num: int) -> None :
        """Prints a title with the device number.

        Args:
            num (int): Integer of the device number.
        """
        print('\n-- Device #'+str(num)+' --\n')
        
    
    def DisplayPODdeviceParameters(self) -> None : 
        """Display all the pod device parameters in a table."""
        # get table
        tab : Texttable|None = self._GetPODdeviceParameterTable()
        if(tab != None) : 
            # print title 
            print('\nParameters for all '+str(self.GetDeviceName())+' Devices:')
            # show table 
            print(tab.draw())


    # ------------ FILE HANDLING ------------


    def SetupFileName(self, fileName: str|None = None) -> None : 
        """Gets the file path and name to save streaming data to. Note that the device name and number \
        will be appended to the end of the filename.

        Args:
            fileName (str | None, optional): Name and path of the file, if known. Defaults to None.
        """
        if(fileName == None) :
            self._saveFileName = UserInput.GetFilePath('\nWhere would you like to save '+self.GetDeviceName()+' streaming data to?', goodExt=self.GetSupportedFileExtensions())
            self.PrintSaveFile()
        else:
            if(UserInput.CheckFileExt(fileName, fIsExt=False, goodExt=self.GetSupportedFileExtensions())) : 
                self._saveFileName = fileName
            else : 
                print('[!] Extension on '+str(fileName)+' is not supported for '+self.GetDeviceName()+' POD devices. Please input a new file name.')
                self.SetupFileName(None)


    def PrintSaveFile(self) -> None :
        """Prints the file path and name that data is saved to. Note that the device name and number \
        will be appended to the end of the filename.
        """
        # print name  
        print('\nStreaming data for '+self.GetDeviceName()+' will be saved to '+ str(self._saveFileName))


    def GetSaveFileName(self) -> str:
        """Gets the path and filename where streaming data is saved to.

        Returns:
            str: String of the save file name and path (_saveFileName).
        """
        return(self._saveFileName)


    def _OpenSaveFile(self, devNum: int) -> IOBase | EdfWriter : 
        """Opens a save file for a given device.

        Args:
            devNum (int): Integer of the device number.

        Returns:
            IOBase | EdfWriter: Opened file. IOBase for a text file, or EdfWriter for EDF file. 
        """
        # get file name and extension 
        fname = self._BuildFileName(devNum)
        p, ext = os.path.splitext(fname)
        # open file based on extension type 
        f = None
        if(ext=='.csv' or ext=='.txt') :    f = self._OpenSaveFile_TXT(fname)
        elif(ext=='.edf') :                 f = self._OpenSaveFile_EDF(fname, devNum)
        return(f)
        

    def _BuildFileName(self, devNum: int) -> str : 
        """Appends the device name and number to the end of the file name. 

        Args:
            devNum (int): Integer of the device number. 

        Returns:
            str: String file name.
        """
        # build file name --> path\filename_<DEVICENAME>_<DEVICE#>.ext 
        #    ex: text.txt --> test_8206-HR_1.txt
        name, ext = os.path.splitext(self._saveFileName)
        fname = name+'_'+self.GetDeviceName()+'_'+str(devNum)+ext   
        return(fname)


    @staticmethod
    def _GetTimeHeader_forTXT() -> str : 
        """Builds a string containing the current date and time to be written to the text file header.

        Returns:
            str: String containing the date and time. Each line begins with '#' and ends with a newline.
        """
        # get time 
        now = datetime.now()
        current_time = str(now.time().strftime('%H:%M:%S'))
        # build string 
        header  = (  '#Today\'s date,'+ now.strftime("%d-%B-%Y")) # shows date
        header += ('\n#Time now,'+ current_time) # shows time
        header += ('\n#GMT,'+ time.strftime("%I:%M:%S %p %Z", time.gmtime()) + '\n') # shows GMT time
        return(header)
    

    # ------------ STREAM ------------ 


    def Stream(self) -> tuple[dict[int,Thread]] | dict[int,Thread] : 
        """Tests that all devices are connected then starts streaming data.

        Raises:
            Exception: Test connection failed.

        Returns:
            tuple[dict[int,Thread]] | dict[int,Thread]: Dictionary with keys as the device number and \
                values as the started Thread. If a tuple, the first item is the Bucket and second is the \
                BucketDrain Threads. 
        """
        # check for good connection 
        if(not self._TestDeviceConnection_All()): 
            raise Exception('Could not stream from '+self.GetDeviceName()+'.')
        # start streaming from all devices 
        else:
            return(self._StreamThreading()) # returns dictionary of all threads with the device# as the keys  


    # ------------ HELPER ------------


    @staticmethod
    def _TestDeviceConnection(pod: Pod) -> bool :
        """Tests if a POD device can be read from or written. Sends a PING command. 

        Args:
            pod (POD_Basics): POD device to read to and write from.

        Returns:
            bool: True for successful connection, false otherwise.
        """
        # returns True when connection is successful, false otherwise
        try:
            pod.FlushPort() # clear out previous packets 
            w: PacketStandard = pod.WritePacket(cmd='PING') # NOTE if a future POD device does not have a PING command, overwrite this function in its class
            r: Packet = pod.ReadPODpacket()
        except:   return(False)
        # check that read matches ping write
        if(w.rawPacket==r.rawPacket): return(True)
        return(False)
        

    def _TestDeviceConnection_All(self) -> bool:
        """Tests the connection of all setup POD devices.

        Returns:
            bool: True when all devices are successfully connected, false otherwise
        """
        allGood = True
        for key,pod in self._podDevices.items(): 
            # test connection of each pod device
            if(not self._TestDeviceConnection(pod)) : 
                # write newline for first bad connection 
                if(allGood==True) : print('') 
                # print error message
                print('[!] Connection issue with '+self.GetDeviceName()+' device #'+str(key)+'.')
                # flag that a connection failed
                allGood = False 
        # return True when all connections are successful, false otherwise
        return(allGood)
    

    @staticmethod
    def _uV(voltage: float|int) -> float :
        """Converts volts to microVolts, rounded to 6 decimal places.

        Args:
            voltage (float | int): number of volts.

        Returns:
            float: voltage in of uV.
        """
        # round to 6 decimal places... add 0.0 to prevent negative zeros when rounding
        return ( round(voltage * 1E-6, 6 ) + 0.0 )