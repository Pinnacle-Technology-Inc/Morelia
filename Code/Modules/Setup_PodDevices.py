"""
Setup_PodDevices allows a user to set up and stream from any number of POD devices. The streamed data is saved to a file
"""

# enviornment imports
import time 
import os
from   threading  import Thread
from   math       import floor 

# local imports
from Setup_8206HR       import Setup_8206HR
from Setup_PodInterface import Setup_Interface

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Setup_PodDevices :     
    

    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self, saveFile:str|None=None, podParametersDict:dict[str,dict|None]|None={'8206-HR':None}) -> None :
        # initialize class instance variables
        self._Setup_PodDevices : dict[str,Setup_Interface] = {  # NOTE add supported devices here 
            '8206-HR' : Setup_8206HR() 
        }
        self._saveFileName : str = ''
        self._options : dict[int,str] = { # NOTE if you change this, be sure to update _DoOption()
            1 : 'Start streaming.',
            2 : 'Show current settings.',
            3 : 'Edit save file path.',
            4 : 'Edit POD device parameters.',
            5 : 'Connect a new POD device.',
            6 : 'Reconnect current POD devices.',
            7 : 'Generate initialization code.', 
            8 : 'Quit.'
        }
        # setup 
        self.SetupPODparameters(podParametersDict)
        self.SetupSaveFile(saveFile)


    def __del__(self) -> None :
        # for each type of POD device 
        for value in self._Setup_PodDevices.values() : 
            if(value != None) : 
                del value
                value = None


    # ============ PUBLIC METHODS ============      ========================================================================================================================


    # ------------ GETTERS ------------


    def GetPODparametersDict(self) -> dict[str, dict[int, dict] ]: 
        allParamDict = {}
        # for each type of device
        for key,value in self._Setup_PodDevices.items() : 
            allParamDict[key] = value.GetPODparametersDict()
        return(allParamDict)


    def GetSaveFileName(self) -> str:
        return(self._saveFileName)
    

    def GetOptions(self) -> dict[int,str] :
        return(self._options)
    

    # ------------ CLASS SETUP ------------


    def SetupPODparameters(self, podParametersDict:dict[str,dict|None]={'8206-HR':None}) -> None :
        # for each type of POD device 
        for key, value in podParametersDict.items() : 
            self._Setup_PodDevices[key].SetupPODparameters(value)


    def SetupSaveFile(self, saveFile:str|None=None) -> None :
        # initialize file name and path 
        if(saveFile == None) :
            self._saveFileName = self._GetFilePath()
            self._PrintSaveFile()
        else:
            self._saveFileName = saveFile
        # setup devices 
        self._SetFilenameToDevices()

    

    # ------------ EXECUTION ------------


    def Run(self) -> None :
        # init looping condition 
        choice = 0
        quit = list(self._options.keys())[list(self._options.values()).index('Quit.')] # abstracted way to get dict key for 'Quit.'
        # keep prompting user until user wants to quit
        while(choice != quit) :
            self._PrintOptions()
            choice = self._AskOption()
            self._DoOption(choice)
    
    
    # ============ PRIVATE METHODS ============      ========================================================================================================================


    # ------------ OPTIONS ------------

    
    def _PrintOptions(self) -> None :
        print('\nOptions:')
        for key,val in self._options.items() : 
            print(str(key)+'. '+val)


    def _AskOption(self) -> int :
        try:
            # get option number from user 
            choice = int(input('\nWhat would you like to do?: '))
        except : 
            # print error and ask again
            print('[!] Please enter an integer number.')
            return(self._AskOption())
        # choice must be an available option 
        if(not choice in self._options.keys()):
            print('[!] Invalid Selection. Please choose an available option.')
            return(self._AskOption())
        # return valid choice
        return(choice)


    def _DoOption(self, choice: int) -> None : 
        # Start Streaming.
        if  (choice == 1): self._Stream()
        # Show current settings.
        elif(choice == 2): self._ShowCurrentSettings()
        # Edit save file path.
        elif(choice == 3): self._EditSaveFilePath()
        # Edit POD device parameters.
        elif(choice == 4): self._EditCheckConnect()
        # Connect a new POD device.
        elif(choice == 5): self._ConnectNewDevice()
        # Reconnect current POD devices.
        elif(choice == 6): self._Reconnect()
        # Generate initialization code.
        elif(choice == 7): self._PrintInitCode()
        # Quit.
        else:              print('\nQuitting...\n')


    def _Stream(self) -> float :
        dt = self._TimeFunc(self._StreamAllDevices)
        print('Execution time:', str(floor(dt)), 'sec') 
        return(dt)


    def _ShowCurrentSettings(self) -> None :
        for podType in self._Setup_PodDevices.values() :
            podType._DisplayPODdeviceParameters()
        self._PrintSaveFile()
    

    def _EditSaveFilePath(self) -> None : 
        self._saveFileName = self._GetFilePath()
        self._SetFilenameToDevices()
        self._PrintSaveFile()


    def _EditCheckConnect(self) -> None :
        for podType in self._Setup_PodDevices.values() :
            podType._DisplayPODdeviceParameters()
            podType._EditParams()
            podType._ValidateParams()
            podType._ConnectAllPODdevices()
        

    def _ConnectNewDevice(self) -> None :
        # get available devices 
        devices = list(self._Setup_PodDevices.keys())
        # ask user for choice if there are more than 1 device type
        if(len(devices) == 1 ) : 
            deviceName = devices[0]
        else:
            print('\nDevice types: '+str(devices))
            deviceName = input('What type of POD device do you want to add?: ')
        # add device if available 
        if(deviceName in devices) : 
            self._Setup_PodDevices[deviceName]._AddPODdevice()
            self._Setup_PodDevices[deviceName]._ValidateParams()
            self._Setup_PodDevices[deviceName]._ConnectAllPODdevices()
        else : 
            print('[!] '+deviceName+' is not available.')
    

    def _Reconnect(self) -> bool :
        areAllGood = True
        for podType in self._Setup_PodDevices.values() :
            # areAllGood is false if any device fails
            areAllGood = areAllGood and podType._ConnectAllPODdevices()
        return(areAllGood)


    def _PrintInitCode(self) -> None :
        print(
            '\n' + 
            'saveFile = r\'' + str(self._saveFileName) + '\'\n' + 
            'podParametersDict = ' + str(self.GetPODparametersDict())  + '\n' + 
            'go = Setup_PodDevices(saveFile, podParametersDict)'  + '\n' + 
            'go.Run()'
        )


    # ------------ FILE HANDLING ------------


    def _PrintSaveFile(self) -> None :
        # print name  
        print('\nStreaming data will be saved to '+ str(self._saveFileName))
 

    @staticmethod
    def _CheckFileExt(f, fIsExt:bool=True, goodExt:list[str]=['.csv','.txt','.edf'], printErr:bool=True) -> bool : 
        # get extension 
        if(not fIsExt) : name, ext = os.path.splitext(f)
        else :  ext = f
        # check if extension is allowed
        if(ext not in goodExt) : 
            if(printErr) : print('[!] Filename must have' + str(goodExt) + ' extension.')
            return(False) # bad extension 
        return(True)      # good extension 


    @staticmethod
    def _GetFilePath() -> str: 
        # ask user for path 
        path = input('\nWhere would you like to save streaming data to?\nPath: ')
        # split into path/name and extension 
        name, ext = os.path.splitext(path)
        # if there is no extension , assume that a file name was not given and path ends with a directory 
        if(ext == '') : 
            # ask user for file name 
            fileName = Setup_PodDevices._GetFileName()
            # add slash if path is given 
            if(name != ''): 
                # check for slash 
                if( ('/' in name) and (not name.endswith('/')) )  :
                    name = name+'/'
                elif(not name.endswith('\\')) : 
                    name = name+'\\'
            # return complete path and filename 
            return(name+fileName)
        # prompt again if bad extension is given 
        elif( not Setup_PodDevices._CheckFileExt(ext)) : return(Setup_PodDevices._GetFilePath())
        # path is correct
        else :
            return(path)


    @staticmethod
    def _GetFileName() -> str:
        # ask user for file name 
        inp = input('File name: ')
        # prompt again if no name given
        if(inp=='') : 
            print('[!] No filename given.')
            return(Setup_PodDevices._GetFileName())
        # get parts 
        name, ext = os.path.splitext(inp)
        # default to csv if no extension is given
        if(ext=='') : ext='.csv'
        # check if extension is correct 
        if( not Setup_PodDevices._CheckFileExt(ext)) : return(Setup_PodDevices._GetFileName())
        # return file name with extension 
        return(name+ext)
    

    def _SetFilenameToDevices(self) -> None :
        # give filename to devices
        for podType in self._Setup_PodDevices.values() : 
            podType.SetFileName(self._saveFileName)


    # ------------ STREAM ------------ 


    def _StreamAllDevices(self) -> None : 
        # start streaming from all devices 
        allThreads = {}
        for key, podType in self._Setup_PodDevices.items() :
            try : 
                allThreads[key] = podType._Stream()
            except Exception as e :
                print('[!]',e)
        # verify that there are open threads 
        if(len(allThreads) != 0) :
            # make thread for user input 
            userThread = Thread(target=self._AskToStopStream)
            userThread.start()
            # wait for threads to finish 
            userThread.join()
            for threadDict in allThreads.values() : # for each device type...
                for thread in threadDict.values() : # for each POD device...
                    thread.join()
            print('Save complete!')
        

    def _AskToStopStream(self) -> None :
        # get any input from user 
        input('\nPress Enter to stop streaming:')
        # tell devices to stop streaming 
        for podType in self._Setup_PodDevices.values() : 
            podType._StopStream()
        print('Finishing up...')


    # ------------ HELPER ------------


    @staticmethod
    def _TimeFunc(func: 'function') -> float: 
        ti = time.time() # start time 
        func() # run function 
        dt = round(time.time()-ti,3) # calculate time difference
        return(dt)