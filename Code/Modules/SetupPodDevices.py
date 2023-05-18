"""
SetupPodDevices allows a user to set up and stream from any number of POD devices. The streamed data is saved to a file
"""

# enviornment imports
from   os           import path      as osp
from   math         import floor 
import threading 
import time 

# local imports
from Setup_8206HR   import Setup_8206HR

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class SetupPodDevices :     
    

    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self, saveFile=None, podParametersDict={'8206-HR':None}) :
        # initialize class instance variables
        self._setupPodDevices = { '8206-HR' : Setup_8206HR() } # NOTE add supporded devices here 
        self._saveFileName = ''
        self._options = { # NOTE if you change this, be sure to update _DoOption()
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


    def __del__(self):
        # for each type of POD device 
        for value in self._setupPodDevices.values() : 
            if(value != None) : 
                del value
                value = None


    # ============ PUBLIC METHODS ============      ========================================================================================================================


    # ------------ GETTERS ------------


    def GetPODparametersDict(self) : 
        allParamDict = {}
        # fir each type of device
        for key,value in self._setupPodDevices.items() : 
            allParamDict[key] = value.GetPODparametersDict()
        return(allParamDict)


    def GetSaveFileName(self):
        return(self._saveFileName)
    

    def GetOptions(self) :
        return(self._options)
    

    # ------------ CLASS SETUP ------------


    def SetupPODparameters(self, podParametersDict={'8206-HR':None}):
        # for each type of POD device 
        for key, value in podParametersDict.items() : 
            self._setupPodDevices[key].SetupPODparameters(value)


    def SetupSaveFile(self, saveFile=None):
        # initialize file name and path 
        if(saveFile == None) :
            self._saveFileName = self._GetFilePath()
            self._PrintSaveFile()
        else:
            self._saveFileName = saveFile
        # setup devices 
        self._SetFilenameToDevices()

    

    # ------------ EXECUTION ------------


    def Run(self) :
        # init looping condition 
        choice = 0
        quit = list(self._options.keys())[list(self._options.values()).index('Quit.')] # abstracted way to get dict key for 'Quit.'
        # keep prompting user until user wants to quit
        while(choice != quit) :
            self._PrintOptions()
            choice = self._AskOption()
            self._DoOption(choice)
    
    
    # ============ PRIVATE METHODS ============      ========================================================================================================================


    # ------------ FILE HANDLING ------------


    def _PrintSaveFile(self):
        # print name  
        print('\nStreaming data will be saved to '+ str(self._saveFileName))
 

    @staticmethod
    def _CheckFileExt(f, fIsExt=True, goodExt=['.csv','.txt','.edf'], printErr=True) : 
        # get extension 
        if(not fIsExt) : name, ext = osp.splitext(f)
        else :  ext = f
        # check if extension is allowed
        if(ext not in goodExt) : 
            if(printErr) : print('[!] Filename must have' + str(goodExt) + ' extension.')
            return(False) # bad extension 
        return(True)      # good extension 


    @staticmethod
    def _GetFilePath() : 
        # ask user for path 
        path = input('\nWhere would you like to save streaming data to?\nPath: ')
        # split into path/name and extension 
        name, ext = osp.splitext(path)
        # if there is no extension , assume that a file name was not given and path ends with a directory 
        if(ext == '') : 
            # ask user for file name 
            fileName = SetupPodDevices._GetFileName()
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
        elif( not SetupPodDevices._CheckFileExt(ext)) : return(SetupPodDevices._GetFilePath())
        # path is correct
        else :
            return(path)


    @staticmethod
    def _GetFileName():
        # ask user for file name 
        inp = input('File name: ')
        # prompt again if no name given
        if(inp=='') : 
            print('[!] No filename given.')
            return(SetupPodDevices._GetFileName())
        # get parts 
        name, ext = osp.splitext(inp)
        # default to csv if no extension is given
        if(ext=='') : ext='.csv'
        # check if extension is correct 
        if( not SetupPodDevices._CheckFileExt(ext)) : return(SetupPodDevices._GetFileName())
        # return file name with extension 
        return(name+ext)
    

    # ------------ STREAM ------------ 


    def _StreamAllDevices(self) : 
        # start streaming from all devices 
        allThreads = {}
        for key, podType in self._setupPodDevices.items() :
            try : 
                allThreads[key] = podType._Stream()
            except Exception as e :
                print('[!]',e)
        # verify that there are open threads 
        if(len(allThreads) != 0) :
            # make thread for user input 
            userThread = threading.Thread(target=self._AskToStopStream)
            userThread.start()
            # wait for threads to finish 
            userThread.join()
            for threadDict in allThreads.values() : # for each device type...
                for thread in threadDict.values() : # for each POD device...
                    thread.join()
            print('Save complete!')
        

    def _SetFilenameToDevices(self) :
        # give filename to devices
        for podType in self._setupPodDevices.values() : 
            podType.SetFileName(self._saveFileName)


    def _AskToStopStream(self):
        # get any input from user 
        input('\nPress Enter to stop streaming:')
        # tell devices to stop streaming 
        for podType in self._setupPodDevices.values() : 
            podType._StopStream()
        print('Finishing up...')


    # ------------ OPTIONS ------------

    
    def _PrintOptions(self):
            print('\nOptions:')
            for key,val in self._options.items() : 
                print(str(key)+'. '+val)


    def _AskOption(self):
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


    def _DoOption(self, choice : int) : 
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


    def _Stream(self) :
        dt = self._TimeFunc(self._StreamAllDevices)
        print('Execution time:', str(floor(dt)), 'sec') 


    def _ShowCurrentSettings(self) :
        for podType in self._setupPodDevices.values() :
            podType._DisplayPODdeviceParameters()
        self._PrintSaveFile()
    

    def _EditSaveFilePath(self) : 
        self._saveFileName = self._GetFilePath()
        self._SetFilenameToDevices()
        self._PrintSaveFile()


    def _EditCheckConnect(self):
        for podType in self._setupPodDevices.values() :
            podType._DisplayPODdeviceParameters()
            podType._EditParams()
            podType._ValidateParams()
            podType._ConnectAllPODdevices()
        

    def _ConnectNewDevice(self):
        for podType in self._setupPodDevices.values() :
            podType._AddPODdevice()
            podType._ValidateParams()
            podType._ConnectAllPODdevices()
    

    def _Reconnect(self):
        for podType in self._setupPodDevices.values() :
            podType._ConnectAllPODdevices()


    def _PrintInitCode(self):
        print(
            '\n' + 
            'saveFile = r\'' + str(self._saveFileName) + '\'\n' + 
            'podParametersDict = ' + str(self.GetPODparametersDict())  + '\n' + 
            'go = Setup_8206HR(saveFile, podParametersDict)'  + '\n' + 
            'go.Run()'
        )


    # ------------ HELPER ------------


    @staticmethod
    def _TimeFunc(func) : 
        ti = time.time() # start time 
        func() # run function 
        dt = round(time.time()-ti,3) # calculate time difference
        return(dt)