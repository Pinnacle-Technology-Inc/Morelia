"""
Setup_Interface provides the basic interface of required methods for subclasses to implement. SetupPodDevices.py is designed to handle any of these children.
"""

# enviornment imports
import os
from   texttable  import Texttable
from   pyedflib   import EdfWriter
from   threading  import Thread
from   io         import IOBase

# local imports
from SerialCommunication    import COM_io
from BasicPodProtocol       import POD_Basics
from GetUserInput           import UserInput

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Setup_Interface : 


    # ============ GLOBAL CONSTANTS ============      ========================================================================================================================

    _NAME    : str = 'GENERIC'  # overwrite this in child classes 
    _PORTKEY : str = 'Port'     # dictionary key for the device's port name 

    # ============ REQUIRED INTERFACE METHODS ============      ========================================================================================================================

    def _IsOneDeviceValid(self, paramDict: dict) -> bool :
        # returns true if the parameters for one POD device is valid, raise Exception otherwise
        pass

    @staticmethod
    def GetDeviceName() -> str : 
        # returns the name of the POD device 
        pass
    
    def _GetParam_onePODdevice(self, forbiddenNames: list[str]) -> dict[str,(str|int|dict)] :
        # Prompts the user to input all device setup parameters
        # should return a dictionary of the device parameters
        pass

    def _GetPODdeviceParameterTable(self) -> Texttable : 
        # get a table that has the parameters for all POD devices 
        pass

    def _ConnectPODdevice(self, deviceNum: int, deviceParams: dict[str,(str|int|dict)]) -> bool : 
        # write setup commands to initialize the POD device with the user's parameters
        # return true for successful connection, false otherwise
        pass

    def _StreamThreading(self) -> dict[int,Thread] :
        # stream data and save data to a file
        # each POD device has its own thread 
        # returns a dictionary with the key as the device# and value as the thread object 
        pass

    def _StopStream(self) -> None: 
        # tell devices to stop streaming 
        pass

    @staticmethod
    def _OpenSaveFile_TXT(fname: str) -> IOBase : 
        # open a text file and write column names 
        # return opened file object
        pass

    def _OpenSaveFile_EDF(self, fname: str, devNum: int) -> EdfWriter :
        # create an EDF file and write all channel information
        # returns the EdfWriter file object 
        pass

    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self) -> None :
        # initialize class instance variables
        self._podDevices : dict[int,POD_Basics]  = {}   # dict of pod device objects. MUST have keys as device#
        self._podParametersDict : dict[int,dict] = {}   # dictionary of device information. MUST have keys as device#, and each value must have {'_PORTKEY': str, ...other values...}
        self._saveFileName : str = ''                   # string filename: <path>/file.ext # the device name and number will be appended to the filename 


    def __del__(self) -> None :
        # delete all POD objects 
        self._DisconnectAllPODdevices


    # ============ PUBLIC METHODS ============      ========================================================================================================================


    def SetFileName(self, fileName: str) -> None :
        self._saveFileName = str(fileName)


    def GetPODparametersDict(self) -> dict[int,dict] :
        return(self._podParametersDict)
    

    def SetupPODparameters(self, podParametersDict:dict[int,dict]|None=None) -> None :
        # get dictionary of POD device parameters
        if(podParametersDict==None):
            self._SetParam_allPODdevices()  # get setup parameters for all POD devices
            self._ValidateParams()          # display parameters and allow user to edit them
        else:
            self._podParametersDict = podParametersDict
        # connect and initialize all POD devices
        self._ConnectAllPODdevices()

    # ------------ VALIDATION ------------
    
    def AreDeviceParamsValid(self, paramDict: None|dict[int,dict]) :
        if(paramDict == None) : 
            return(True)
        # is params a dict?
        if(not isinstance(paramDict, dict)) :
            raise Exception('[!] Invalid value type in parameter dictionary.')
        # are keys int and value dict
        allGood = True 
        for key,value in paramDict.items() : 
            if(not isinstance(key,int)) : 
                raise Exception('[!] Device keys must be integer type for '+str(self._NAME)+'.')
            if(not isinstance(value,dict)) : 
                raise Exception('[!] Device parameters must be dictionary type for '+str(self._NAME)+'.')
            if(len(value)==0) : 
                raise Exception('[!] Device parameters dictionary is empty for '+str(self._NAME)+'.')
            # check values 
            allGood = allGood and self._IsOneDeviceValid(value)
        # no exceptions raised
        return(allGood)
    
    # ============ PRIVATE METHODS ============      ========================================================================================================================


    # ------------ DEVICE CONNECTION ------------


    @staticmethod
    def _SetNumberOfDevices(name: str) -> int : 
        try : 
            # request user imput
            n = int(input('\nHow many '+str(name)+' devices do you want to use?: '))
            # number must be positive
            if(n<=0):
                print('[!] Number must be greater than zero.')
                return(Setup_Interface._SetNumberOfDevices(name))
            # return number of POD devices 
            return(n)
        except : 
            # print error and start over
            print('[!] Please enter an integer number.')
            return(Setup_Interface._SetNumberOfDevices(name))
        

    def _ConnectAllPODdevices(self) -> bool : 
        # delete existing 
        self._DisconnectAllPODdevices()
        # connect new devices
        print('\nConnecting POD devices...')
        # setup each POD device
        areAllGood = True
        for key,val in self._podParametersDict.items():
           # areAllGood is false if any device fails
           areAllGood = areAllGood and self._ConnectPODdevice(key,val)
        return(areAllGood)


    def _DisconnectAllPODdevices(self) -> None :
        for k in list(self._podDevices.keys()) : 
            pod = self._podDevices.pop(k)
            del pod # port closed on delete in COM_io


    def _AddPODdevice(self) -> None :
        nextNum = max(self._podParametersDict.keys())+1
        self._PrintDeviceNumber(nextNum)
        self._podParametersDict[nextNum] = self._GetParam_onePODdevice(self._GetForbiddenNames(key=self._PORTKEY))


    # ------------ SETUP POD PARAMETERS ------------


    def _SetParam_allPODdevices(self) -> None :
        # get the number of devices 
        numDevices = self._SetNumberOfDevices(self._NAME)
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
            portNames[i] = onePodDict[self._PORTKEY]
            podDict[i+1] = onePodDict
        # save dict containing information to setup all POD devices
        self._podParametersDict = podDict


    @staticmethod
    def _ChoosePort(forbidden:list[str]=[]) -> str : 
        # get ports
        portList = Setup_Interface._GetPortsList(forbidden)
        print('Available COM Ports:', portList)
        # request port from user
        choice = input('Select port: COM')
        # choice cannot be an empty string
        if(choice == ''):
            print('[!] Please choose a COM port.')
            return(Setup_Interface._ChoosePort(forbidden))
        else:
            # search for port in list
            for port in portList:
                if port.startswith('COM'+choice):
                    return(port)
            # if return condition not reached...
            print('[!] COM'+choice+' does not exist. Try again.')
            return(Setup_Interface._ChoosePort(forbidden))

        
    @staticmethod
    def _GetPortsList(forbidden:list[str]=[]) -> list[str] : 
        # get port list 
        portListAll = COM_io.GetCOMportsList()
        if(forbidden):
            # remove forbidden ports
            portList = [x for x in portListAll if x not in forbidden]
        else:
            portList = portListAll
        # check if the list is empty 
        if (len(portList) == 0):
            # print error and keep trying to get ports
            print('[!] No COM ports in use. Please plug in POD device.')
            while(len(portList) == 0) : 
                portListAll = COM_io.GetCOMportsList()
                portList = [x for x in portListAll if x not in forbidden]
        # return port
        return(portList)
    

    # ------------ EDIT POD PARAMETERS ------------


    def _ValidateParams(self) -> None : 
        # display all pod devices and parameters
        self._DisplayPODdeviceParameters()
        # ask if params are good or not
        validParams = UserInput.AskYN(question='Are the '+self._NAME+' device parameters correct?')
        # edit if the parameters are not correct 
        if(not validParams) : 
            self._EditParams()
            self._ValidateParams()


    def _EditParams(self) -> None :
        # chose device # to edit
        editThis = self._SelectPODdeviceFromDictToEdit()
        # get all port names except for device# to be edited
        forbiddenNames = self._GetForbiddenNames(exclude=self._podParametersDict[editThis][self._PORTKEY], key=self._PORTKEY)
        # edit device
        self._PrintDeviceNumber(editThis)
        self._podParametersDict[editThis] = self._GetParam_onePODdevice(forbiddenNames)


    def _SelectPODdeviceFromDictToEdit(self) -> int :
        podKey = UserInput.AskForInt('Edit '+self._NAME+' device #')
        # check is pod device exists
        keys = self._podParametersDict.keys()
        if(podKey not in keys) : 
            print('[!] Invalid POD device number. Please try again.')
            return(self._SelectPODdeviceFromDictToEdit())
        else:
            # return the pod device number
            return(podKey)
        

    def _GetForbiddenNames(self, key:str='Port', exclude:str|None=None) -> list[str] :
        if(exclude == None) : 
            # get port name for each POD device 
            portNames = [x[key] for x in self._podParametersDict.values()]
        else :
            portNames = [x[key] for x in self._podParametersDict.values() if exclude != x[key]]
        return(portNames)
    

    # ------------ DISPLAY POD PARAMETERS ------------
       

    @staticmethod
    def _PrintDeviceNumber(num: int) -> None :
        print('\n-- Device #'+str(num)+' --\n')
        
    
    def _DisplayPODdeviceParameters(self) -> None : 
        # get table
        tab : Texttable|None = self._GetPODdeviceParameterTable()
        if(tab != None) : 
            # print title 
            print('\nParameters for all '+str(self._NAME)+' Devices:')
            # show table 
            print(tab.draw())


    # ------------ FILE HANDLING ------------


    def _OpenSaveFile(self, devNum: int) -> IOBase | EdfWriter : 
        # get file name and extension 
        fname = self._BuildFileName(devNum)
        p, ext = os.path.splitext(fname)
        # open file based on extension type 
        f = None
        if(ext=='.csv' or ext=='.txt') :    f = self._OpenSaveFile_TXT(fname)
        elif(ext=='.edf') :                 f = self._OpenSaveFile_EDF(fname, devNum)
        return(f)
    

    def _BuildFileName(self, devNum: int) -> str : 
        # build file name --> path\filename_<DEVICENAME>_<DEVICE#>.ext 
        #    ex: text.txt --> test_8206-HR_1.txt
        name, ext = os.path.splitext(self._saveFileName)
        fname = name+'_'+self._NAME+'_'+str(devNum)+ext   
        return(fname)

    # ------------ STREAM ------------ 


    def _Stream(self) -> dict[int,Thread] : 
        # check for good connection 
        if(not self._TestDeviceConnection_All()): 
            raise Exception('Could not stream from '+self._NAME+'.')
        # start streaming from all devices 
        else:
            return(self._StreamThreading()) # returns dictionary of all threads with the device# as the keys
    

  


    # ------------ HELPER ------------


    @staticmethod
    def _TestDeviceConnection(pod: POD_Basics) -> bool :
        # returns True when connection is successful, false otherwise
        try:
            w = pod.WritePacket(cmd='PING') # NOTE if a future POD device does not have a PING command, move this function into the relevant subclasses
            r = pod.ReadPODpacket()
        except:     
            return(False)
        # check that read matches ping write
        if(w==r):   
            return(True)
        else:       
            return(False)
        

    def _TestDeviceConnection_All(self) -> bool:
        allGood = True
        for key,pod in self._podDevices.items(): 
            # test connection of each pod device
            if(not self._TestDeviceConnection(pod)) : 
                # write newline for first bad connection 
                if(allGood==True) : print('') 
                # print error message
                print('Connection issue with POD device #'+str(key)+'.')
                # flag that a connection failed
                allGood = False 
        # return True when all connections are successful, false otherwise
        return(allGood)
    

    @staticmethod
    def _uV(voltage: float|int) :
        # round to 6 decimal places... add 0.0 to prevent negative zeros when rounding
        return ( round(voltage * 1E-6, 6 ) + 0.0 )
    