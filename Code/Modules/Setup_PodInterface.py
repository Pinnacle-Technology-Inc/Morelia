"""
Setup_Interface provides the basic interface of required methods for subclasses to implement. SetupPodDevices.py is designed to handle any of these children.
"""

# enviornment imports
import math 
import time 
from   os       import path      as osp

# local imports
from SerialCommunication    import COM_io
from BasicPodProtocol       import POD_Basics

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Setup_Interface : 


    # ============ GLOBAL CONSTANTS ============      ========================================================================================================================

    _NAME = ''
    _PORTKEY = ''

    # ============ REQUIRED INTERFACE METHODS ============      ========================================================================================================================

    def _GetParam_onePODdevice(self, forbiddenNames) : 
        pass

    def _DisplayPODdeviceParameters(self) : 
        pass

    def _ConnectPODdevice(self, deviceNum : int, deviceParams : dict) : 
        pass

    def _StreamThreading(self) :
        pass

    def _StopStream(self) : 
        pass

    @staticmethod
    def _OpenSaveFile_TXT(fname) : 
        pass

    def _OpenSaveFile_EDF(self, fname, devNum):
        pass

    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self) :
        # initialize class instance variables
        self._podDevices = {}           # dict of pod device objects. MUST have keys as device#
        self._podParametersDict = {}    # dictionary of device information. MUST have keys as device#, and each value must have {'_PORTKEY': str, ...}
        self._saveFileName = ''         # string filename: <path>/file_<DEVICE#>.ext # the device number will be appended to the filename 


    def __del__(self):
        # delete all POD objects 
        self._DisconnectAllPODdevices


    # ============ PUBLIC METHODS ============      ========================================================================================================================


    def SetFileName(self, fileName : str) :
        self._saveFileName = str(fileName)


    def GetPODparametersDict(self) :
        return(self._podParametersDict)
    

    def SetupPODparameters(self, podParametersDict=None):
        # get dictionary of POD device parameters
        if(podParametersDict==None):
            self._SetParam_allPODdevices()  # get setup parameters for all POD devices
            self._ValidateParams()          # display parameters and allow user to edit them
        else:
            self._podParametersDict = podParametersDict
        # connect and initialize all POD devices
        self._ConnectAllPODdevices()


    # ============ PRIVATE METHODS ============      ========================================================================================================================


    # ------------ DEVICE CONNECTION ------------


    @staticmethod
    def _SetNumberOfDevices(name : str) : 
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
        

    def _ConnectAllPODdevices(self) : 
        # delete existing 
        self._DisconnectAllPODdevices()
        # connect new devices
        print('\nConnecting POD devices...')
        # setup each POD device
        for key,val in self._podParametersDict.items():
           self._ConnectPODdevice(key,val)


    def _DisconnectAllPODdevices(self) :
        for k in list(self._podDevices.keys()) : 
            pod = self._podDevices.pop(k)
            del pod # port closed on delete in COM_io


    def _AddPODdevice(self):
        nextNum = max(self._podParametersDict.keys())+1
        self._PrintDeviceNumber(nextNum)
        self._podParametersDict[nextNum] = self._GetParam_onePODdevice(self._GetForbiddenNames())


    # ------------ SETUP POD PARAMETERS ------------


    def _SetParam_allPODdevices(self) :
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
            portNames[i] = onePodDict['Port']
            podDict[i+1] = onePodDict
        # save dict containing information to setup all POD devices
        self._podParametersDict = podDict


    @staticmethod
    def _ChoosePort(forbidden=[]) : 
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
    def _GetPortsList(forbidden=[]) : 
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


    def _ValidateParams(self) : 
        # display all pod devices and parameters
        self._DisplayPODdeviceParameters()
        # ask if params are good or not
        validParams = Setup_Interface._AskYN(question='Are the '+self._NAME+' device parameters correct?')
        # edit if the parameters are not correct 
        if(not validParams) : 
            self._EditParams()
            self._ValidateParams()

    def _EditParams(self) :
        # chose device # to edit
        editThis = self._SelectPODdeviceFromDictToEdit()
        # get all port names except for device# to be edited
        forbiddenNames = self._GetForbiddenNames(exclude=self._podParametersDict[editThis][self._PORTKEY], key=self._PORTKEY)
        # edit device
        self._PrintDeviceNumber(editThis)
        self._podParametersDict[editThis] = self._GetParam_onePODdevice(forbiddenNames)


    def _SelectPODdeviceFromDictToEdit(self):
        try:
            # get pod device number from user 
            podKey = int(input('Edit '+self._NAME+' device #: '))
        except : 
            # print error and start over
            print('[!] Please enter an integer number.')
            return(self._SelectPODdeviceFromDictToEdit())

        # check is pod device exists
        keys = self._podParametersDict.keys()
        if(podKey not in keys) : 
            print('[!] Invalid POD device number. Please try again.')
            return(self._SelectPODdeviceFromDictToEdit())
        else:
            # return the pod device number
            return(podKey)
        

    def _GetForbiddenNames(self, key='Port', exclude=None):
        if(exclude == None) : 
            portNames = [x[key] for x in self._podParametersDict.values()]
        else :
            portNames = [x[key] for x in self._podParametersDict.values() if exclude != x[key]]
        return(portNames)
    

    # ------------ DISPLAY POD PARAMETERS ------------
       

    @staticmethod
    def _PrintDeviceNumber(num : int):
        print('\n-- Device #'+str(num)+' --\n')


    @staticmethod
    def _AskYN(question : str) : 
        response = input(str(question)+' (y/n): ').upper() 
        if(response=='Y' or response=='YES'):
            return(True)
        elif(response=='N' or response=='NO'):
            return(False)
        else:
            print('[!] Please enter \'y\' or \'n\'.')
            return(Setup_Interface._AskYN(question))
        

    # ------------ FILE HANDLING ------------


    def _OpenSaveFile(self, devNum) : 
        # get file name and extension 
        fname = self._BuildFileName(devNum)
        p, ext = osp.splitext(fname)
        # open file based on extension type 
        f = None
        if(ext=='.csv' or ext=='.txt') :    f = self._OpenSaveFile_TXT(fname)
        elif(ext=='.edf') :                 f = self._OpenSaveFile_EDF(fname, devNum)
        return(f)
    

    def _BuildFileName(self, devNum : int) : 
        # build file name --> path\filename_<DEVICENAME>_<DEVICE#>.ext 
        #    ex: text.txt --> test_8206-HR_1.txt
        name, ext = osp.splitext(self._saveFileName)
        fname = name+'_'+self._NAME+'_'+str(devNum)+ext   
        return(fname)

    # ------------ STREAM ------------ 


    def _Stream(self) : 
        # check for good connection 
        if(not self._TestDeviceConnection_All()): 
            raise Exception('Could not stream from '+self._NAME+'.')
        # start streaming from all devices 
        else:
            return(self._StreamThreading()) # returns dictionary of all threads with the device# as the keys
    

    # ------------ HELPER ------------


    @staticmethod
    def _TestDeviceConnection(pod : POD_Basics):
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
        

    def _TestDeviceConnection_All(self) :
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
    