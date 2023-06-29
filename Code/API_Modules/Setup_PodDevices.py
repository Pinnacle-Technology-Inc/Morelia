

# enviornment imports
import time 
import os
from   threading  import Thread
from   math       import floor 

# local imports
from Setup_PodInterface import Setup_Interface
from Setup_8206HR       import Setup_8206HR
from Setup_8401HR       import Setup_8401HR
from Setup_8480HR       import Setup_8480HR
from GetUserInput       import UserInput

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Setup_PodDevices :     
    """
    Setup_PodDevices allows a user to set up and stream from any number of POD devices. The streamed \
    data is saved to a file.
    
    REQUIRES FIRMWARE 1.0.2 OR HIGHER.

    Attributes:
        _Setup_PodDevices (dict[str,Setup_Interface]): Dictionary containing the Setup_Interface \
            subclasses for each POD device.
        _saveFileName (str): String containing the path, filename, and file extension to a file to \
            save streaming data to. The filename will be extended with "_<DEVICE NAME>_<DEVICE NUMBER>" \
            for each device. 
        _options (dict[int,str]): Dictionary listing the different options for the user to complete.
    """

    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self, saveFile:str|None=None, podParametersDict:dict[str,dict|None]|None=None) -> None :
        """Initializes the class. Sets the default values of the class instance variables. Calls \
        functions to complete the class setup.

        Args:
            saveFile (str | None, optional): String describing the directory path and filename with an \
                extension. Defaults to None.
            podParametersDict (dict[str,dict | None] | None, optional): Dictionary of POD devices and \
                their respective initialization dictionaries. Defaults to None.
        """
        # initialize class instance variables
        self._Setup_PodDevices : dict[str,Setup_Interface] = {} 
        self._saveFileName : str = ''
        self._options : dict[int,str] = { # NOTE if you change this, be sure to update _DoOption()
            1 : 'Start streaming.',
            2 : 'Show current settings.',
            3 : 'Edit save file path.',
            4 : 'Edit POD device parameters.',
            5 : 'Remove a POD device.',
            6 : 'Connect a new POD device.',
            7 : 'Reconnect current POD devices.',
            8 : 'Generate initialization code.', 
            9 : 'Quit.'
        }
        # choose devices to use 
        params = self._GetParams(podParametersDict)
        # setup devices  
        self.SetupPODparameters(params)
        self.SetupSaveFile(saveFile)


    def __del__(self) -> None :
        """Deletes all POD device setup objects."""
        # for each type of POD device 
        for value in self._Setup_PodDevices.values() : 
            if(value != None) : 
                del value
                value = None


    # ============ PUBLIC METHODS ============      ========================================================================================================================


    # ------------ GETTERS ------------


    def GetPODparametersDict(self) -> dict[str, dict[int, dict] ]: 
        """Sets up each POD device type. Used in initialization.

        Returns:
            dict[str, dict[int, dict] ]: Dictionary of all POD devices initialization. The keys are the \
                device name and the entries are the initialization dictionaries. 
        """
        allParamDict = {}
        # for each type of device
        for key,value in self._Setup_PodDevices.items() : 
            allParamDict[key] = value.GetPODparametersDict()
        return(allParamDict)


    def GetSaveFileName(self) -> str:
        """Gets the name of the class object's save file.

        Returns:
            str: String of the save file name and path (_saveFileName).
        """
        return(self._saveFileName)
    

    def GetOptions(self) -> dict[int,str] :
        """Gets the dictionary of setup options.

        Returns:
            dict[int,str]: Dictionary listing the different options for the user to complete (_options).
        """
        return(self._options)
    

    # ------------ CLASS SETUP ------------


    def SetupPODparameters(self, podParametersDict:dict[str,dict|None]) -> None :
        """Sets up each POD device type. Used in initialization.

        Args:
            podParametersDict (dict[str,dict | None]): Dictionary of all POD devices initialization. \
                The keys are the device name and the entries are the initialization dictionaries. 
        """
        # for each type of POD device 
        for key, value in podParametersDict.items() : 
            self._Setup_PodDevices[key].SetupPODparameters(value)


    def SetupSaveFile(self, saveFile:str|None=None) -> None :
        """Gets the path/file name from the user and stores it. Used in initialization.

        Args:
            saveFile (str | None, optional): String of the save file, which includes the directory path, \
                filename, and file extension. Defaults to None.
        """
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
        """Prints the options and askes the user what to do. Loops until 'Quit" is chosen."""
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
        """Prints options available for user."""
        print('\nOptions:')
        for key,val in self._options.items() : 
            print(str(key)+'. '+val)


    def _AskOption(self) -> int :
        """Asks user which option to do.

        Returns:
            int: Integer number representing an option key.
        """
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
        """Performs the methods associated with the user selected option.

        Args:
            choice (int): Integer number representing an option key.
        """
        match choice : 
            case 1 : self._Stream()                 # Start Streaming.
            case 2 : self._ShowCurrentSettings()    # Show current settings.
            case 3 : self._EditSaveFilePath()       # Edit save file path.
            case 4 : self._EditCheckConnect()       # Edit POD device parameters.
            case 5 : self._RemoveDevice()           # Remove POD device.
            case 6 : self._ConnectNewDevice()       # Connect a new POD device.
            case 7 : self._Reconnect()              # Reconnect current POD devices.
            case 8 : self._PrintInitCode()          # Generate initialization code.
            case _ : print('\nQuitting...\n')       # Quit.


    def _Stream(self) -> float :
        """Streams data from all POD devices and prints the execution time. 

        Returns:
            float: Float of the execution time in seconds.
        """
        dt = self._TimeFunc(self._StreamAllDevices)
        print('Execution time:', str(floor(dt)), 'sec') 
        return(dt)


    def _ShowCurrentSettings(self) -> None :
        """Displays the POD device settings for all devices, and then prints the save file name."""
        for podType in self._Setup_PodDevices.values() :
            podType.DisplayPODdeviceParameters()
        self._PrintSaveFile()
    

    def _EditSaveFilePath(self) -> None : 
        """Asks the user for the POD device type, then asks the user for a new file name and path, \
        then sets the value to the POD devices.
        """
        self._saveFileName = self._GetFilePath()
        self._saveFileName = self._SetFilenameToDevices()
        self._PrintSaveFile()


    def _EditCheckConnect(self) -> None :
        """Displays the POD devices parameters, asks the user to edit the device, and then reconnects \
        the device for each POD device type. 
        """
        deviceName = self._GetChosenDeviceType('What type of POD device do you want to edit?')
        # edit device if available 
        if(deviceName in self._Setup_PodDevices) :
            self._Setup_PodDevices[deviceName].DisplayPODdeviceParameters()
            self._Setup_PodDevices[deviceName]._EditParams()
            self._Setup_PodDevices[deviceName]._ValidateParams()
            self._Setup_PodDevices[deviceName].ConnectAllPODdevices()
        else : 
            print('[!] '+deviceName+' is not available.')


    def _RemoveDevice(self) -> None : 
        """Displays the POD devices parameters, asks the user which device ro remove, and then \
        deletes that POD device.
        """
        deviceName = self._GetChosenDeviceType('What type of POD device do you want to remove?')
        # remove device if available 
        if(deviceName in self._Setup_PodDevices) :
            self._Setup_PodDevices[deviceName].DisplayPODdeviceParameters()
            self._Setup_PodDevices[deviceName]._RemoveDevice()
        else : 
            print('[!] '+deviceName+' is not available.')


    def _ConnectNewDevice(self) -> None :
        """Asks the user for the POD device type, then it sets up that device."""
        deviceName = self._GetChosenDeviceType('What type of POD device do you want to add?')
        # add device if available 
        if(deviceName in self._Setup_PodDevices) : 
            self._Setup_PodDevices[deviceName]._AddPODdevice()
            self._Setup_PodDevices[deviceName]._ValidateParams()
            self._Setup_PodDevices[deviceName].ConnectAllPODdevices()
        else : 
            print('[!] '+deviceName+' is not available.')
    

    def _Reconnect(self) -> bool :
        """Reconnects all POD devices.

        Returns:
            bool: Bool that is true if all devices were successfully connected. False otherwise.
        """
        areAllGood = True
        for podType in self._Setup_PodDevices.values() :
            # areAllGood is false if any device fails
            thisGood = podType.ConnectAllPODdevices()
            areAllGood = areAllGood and thisGood
        return(areAllGood)


    def _PrintInitCode(self) -> None :
        """Prints code that can be used to initialize and run SetupPodDevices with the \
        current parameters.
        """
        print(
            '\n' + 
            'saveFile = r\'' + str(self._saveFileName) + '\'\n' + 
            'podParametersDict = ' + str(self.GetPODparametersDict())  + '\n' + 
            'go = Setup_PodDevices(saveFile, podParametersDict)'  + '\n' + 
            'go.Run()'
        )


    # ------------ INIT ------------    


    def _GetParams(self, podParametersDict: None|dict[str,None]) -> dict[str,dict|None]: 
        """If no parameters are give, this asks user which types of POD devices they want to use. \
        Then it checks if the parameters are valid. 

        Args:
            podParametersDict (None | dict[str,None]): Dictionary of all POD devices initialization. \
                The keys are the device name and the entries are the initialization dictionaries. 

        Returns:
            dict[str,dict|None]: Dictionary whose keys are the POD device name, and value the setup \
                dictionary. 
        """
        # setup parameters
        if(podParametersDict == None) : 
            # return dictionary with POD device names as keys and None as values 
            params = Setup_PodDevices._AskUserForDevices()
        else:
            params = podParametersDict
        # validation 
        self._Set_Setup_PodDevices(params)
        self._CheckForValidParams(params)
        # return valid dict 
        return(params)
        

    @staticmethod
    def _AskUserForDevices() :  # NOTE add all supported devices here 
        """Asks the user what POD devices they want to use."""
        useParams = {}
        name = Setup_8206HR.GetDeviceName()
        if(UserInput.AskYN('\nWill you be using any '+str(name)+' devices?')) :
            useParams[name] = None
        name = Setup_8401HR.GetDeviceName()
        if(UserInput.AskYN('Will you be using any '+str(name)+' devices?')) :
            useParams[name] = None
        name = Setup_8480HR.GetDeviceName()
        if(UserInput.AskYN('Will you be using any '+str(name)+' devices?')) :
            useParams[name] = None
        # ask again if user responds No to all 
        if(len(useParams) == 0 ) : 
            print('[!] No POD devices selected. Please choose at least one device.')
            return(Setup_PodDevices._AskUserForDevices())
        # return dictionary with POD device names as keys and None as values 
        return(useParams)
    
        
    def _CheckForValidParams(self, podParametersDict: dict[str,None|dict]) -> bool :
        """Checks if the parameters are correctly formatted.

        Args:
            podParametersDict (dict[str,None | dict]): Dictionary with keys as the device names and \
                values as None or the respective parameter dictionary.

        Raises:
            Exception: Parameters must be dictionary type.
            Exception: Parameters dictionary is empty.
            Exception: Invalid device name in paramater dictionary.

        Returns:
            bool: True if the parameters are correctly formatted.
        """
        # is params a dictionary?
        if(not isinstance(podParametersDict,dict)) : 
            raise Exception('[!] Parameters must be dictionary type.')
        # if so, is the dictionary empty?
        if(len(podParametersDict) == 0) : # empty dict
            raise Exception('[!] Parameters dictionary is empty.')
        # for each dict entry...
        allGood = True 
        goodKeys = (Setup_8206HR.GetDeviceName(), Setup_8401HR.GetDeviceName(), Setup_8480HR.GetDeviceName()) # NOTE add all supported devices here 
        for key,value in podParametersDict.items()  :
            # is the key a POD device name?
            if(key not in goodKeys) : # device not supported
                raise Exception('[!] Invalid device name in paramater dictionary: '+str(key)+'.')
            # is the value correct for the device?
            thisGood = self._Setup_PodDevices[key].AreDeviceParamsValid(value)
            allGood = allGood and thisGood # becomes false if any device is invalid 
        # should return true if no exceptions raised  
        return(allGood)


    def _Set_Setup_PodDevices(self, podParametersDict:dict[str,dict|None]) -> None : # NOTE add all supported devices here 
        """Sets the _Setup_PodDevices varaible to have keys as the POD device name and values \
        as the setup class.

        Args:
            podParametersDict (dict[str,dict | None]): Dictionary with keys as the device names \
                and values as None or the respective parameter dictionary.
        """
        # use select devices        
        name = Setup_8206HR.GetDeviceName()
        if(name in podParametersDict ) : 
            self._Setup_PodDevices[name] = Setup_8206HR()
        name = Setup_8401HR.GetDeviceName()
        if(name in podParametersDict) : 
            self._Setup_PodDevices[name] = Setup_8401HR()
        name = Setup_8480HR.GetDeviceName()
        if(name in podParametersDict) : 
            self._Setup_PodDevices[name] = Setup_8480HR()
        
        


    # ------------ FILE HANDLING ------------


    def _PrintSaveFile(self) -> None :
        """Prints the file path and name that data is saved to. Note that the device name and number \
        will be appended to the end of the filename,
        """
        # print name 
        print('\nStreaming data will be saved to '+ str(self._saveFileName))
        # if setup 8480 print special filename also 
        # OR for each POD Interface child, print save file 
 

    @staticmethod
    def _CheckFileExt(f: str, fIsExt:bool=True, goodExt:list[str]=['.csv','.txt','.edf'], printErr:bool=True) -> bool : 
        """_summary_

        Args:
            f (str): file name or extension
            fIsExt (bool, optional): Boolean flag that is true if f is an extension, false \
                otherwise. Defaults to True.
            goodExt (list[str], optional): List of valid file extensions. Defaults to \
                ['.csv','.txt','.edf'].
            printErr (bool, optional): Boolean flag that, when true, will print an error \
                statement. Defaults to True.

        Returns:
            bool: True if extension is in goodExt list, False otherwise.
        """
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
        """Asks user for a path and filename to save streaming data to.

        Returns:
            str: String of the file path, name, and extension.
        """
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
        """Asks the user for a filename.

        Returns:
            str: String of the file name and extension.
        """
        # ask user for file name 
        print("PLEASE NOTE: Only .txt files are permitted for POD device 8480-HR. Any other extensions given will automatically be changed to .txt")
        # added the above warning to users so Only txt files are allowed for 8480-HR.
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
        """Sets the filename to each POD device type."""
        # give filename to devices
        for podType in self._Setup_PodDevices.values() : 
            podType.SetFileName(self._saveFileName)
  


    # ------------ STREAM ------------ 


    def _StreamAllDevices(self) -> None : 
        """Streams data from all the devices. User is asked to click enter to stop streaming. \
        Data is saved to file. Uses threading.
        """
        # start streaming from all devices 
        allThreads = {}
        for key, podType in self._Setup_PodDevices.items() :
            try : 
                allThreads[key] = podType.Stream()
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
        """Asks user to press enter to stop streaming. The program will then prompt all POD \
        devices to end stream.
        """
        # get any input from user 
        input('\nPress Enter to stop streaming:')
        # tell devices to stop streaming 
        for podType in self._Setup_PodDevices.values() : 
            podType.StopStream()
        print('Finishing up...')


    # ------------ HELPER ------------


    @staticmethod
    def _TimeFunc(func: 'function') -> float : 
        """Runs a function and gets the calculated execultion time.

        Args:
            func (function): Function/method name.

        Returns:
            float: Float of the execution time in seconds rounded to 3 decimal places.
        """
        ti = time.time() # start time 
        func() # run function 
        dt = round(time.time()-ti,3) # calculate time difference
        return(dt)
    

    def _GetChosenDeviceType(self, question: str) -> str : 
        """Asks the user which type of POD device they want.

        Args:
            question (str): Question to ask the user.

        Returns:
            str: String of the user input (may be invalid POD device type).
        """
        # get available devices 
        devices = list(self._Setup_PodDevices.keys())
        # ask user for choice if there are more than 1 device type
        if(len(devices) == 1 ) : 
            deviceName = devices[0]
        else:
            print('\nPOD devices: '+', '.join(devices))
            deviceName = input(question+': ')
        return(deviceName)