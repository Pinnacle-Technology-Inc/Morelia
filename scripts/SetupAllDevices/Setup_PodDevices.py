# enviornment imports
import time 
from   threading    import Thread
from   math         import floor 

# local imports
from Setup.Inputs           import UserInput
from Setup.SetupOneDevice   import SetupInterface, Setup8206HR, Setup8401HR, Setup8229, Setup8480SC, Setup8274D
from Morelia.Parameters     import Params

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class SetupAll :     
    """
    Setup_PodDevices allows a user to set up and stream from any number of POD devices. The streamed \
    data is saved to a file.
    
    REQUIRES FIRMWARE 1.0.2 OR HIGHER.

    Attributes:
        _Setup_PodDevices (dict[str,dict[int,Params_Interface]): Dictionary containing the Setup_Interface \
            subclasses for each POD device.
        _options (dict[int,str]): Dictionary listing the different options for the user to complete.
    """

    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self, saveFileDict:dict[str,str]|None=None, podParametersDict:dict[str,dict[int,Params]|None]|None=None) -> None :
        """Initializes the class. Sets the default values of the class instance variables. Calls \
        functions to complete the class setup.

        Args:
            saveFileDict (dict[str, str] | None, optional): Dictionary with keys are the POD device names and values \
                as the file names. Defaults to None.
            podParametersDict (dict[int, Params_Interface] | None] | None, optional): Dictionary of POD devices and \
                their respective parameters. Defaults to None.
        """
        # initialize class instance variables
        self._Setup_PodDevices : dict[str,SetupInterface] = {} 
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
        # setup devices  
        self.SetupPODparameters(self._GetParams(podParametersDict))
        self.SetupSaveFile(saveFileDict)


    def __del__(self) -> None :
        """Deletes all POD device setup objects."""
        # for each type of POD device 
        for value in self._Setup_PodDevices.values() : 
            if(value != None) : 
                del value
                value = None


    # ============ PUBLIC METHODS ============      ========================================================================================================================


    # ------------ GETTERS ------------


    def GetPODparametersInit(self) -> str : 
        """Sets up each POD device type. Used in initialization.
        Returns:
            str: String representing a dictionary of all POD devices initialization. The keys are the \
                device name and the entries are the initialization dictionaries. 
        """
        allInitParams = '{'
        # for each type of device
        for key,val in self._Setup_PodDevices.items() : 
            allInitParams += ' \''+key+'\' : '+val.GetPODparametersInit()+','
        # cut off last comma and add close bracket 
        allInitParams = allInitParams[:-1] + ' }' 
        return(allInitParams)


    def GetSaveFileNames(self) -> dict[str]:
        """Gets a dictionary of the save files names for all connected POD devices.

        Returns:
            dict[str]: Dictionary of the save file name and path for all devices.
        """
        fileNames = {}
        for key,val in self._Setup_PodDevices.items() : 
            fileNames[key] = val.GetSaveFileName()
        return(fileNames)
    

    def GetOptions(self) -> dict[int,str] :
        """Gets the dictionary of setup options.

        Returns:
            dict[int,str]: Dictionary listing the different options for the user to complete (_options).
        """
        return(self._options)
    

    # ------------ CLASS SETUP ------------


    def SetupPODparameters(self, podParametersDict:dict[str,dict[int,Params]|None]) -> None :
        """Sets up each POD device type. Used in initialization.

        Args:
            podParametersDict (dict[str,dict[int,Params_Interface] | None]): Dictionary of all POD devices initialization. \
                The keys are the device name and the entries are the initialization dictionaries. 
        """
        # for each type of POD device 
        for key, value in podParametersDict.items() : 
            self._Setup_PodDevices[key].SetupPODparameters(value)


    def SetupSaveFile(self, saveFileDict:dict[str,str]|None=None) -> None :
        """Gets the path/file name from the user and stores it. Used in initialization.

        Args:
            saveFile (dict[str,str|None] | None, optional): String of the save file, which includes the directory path, \
                filename, and file extension. Defaults to None.
        """
        if(saveFileDict == None ) : 
            for val in self._Setup_PodDevices.values() : 
                val.SetupFileName(None)
        else: 
            for key, value in saveFileDict.items() : 
                self._Setup_PodDevices[key].SetupFileName(value)
    

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
            podType.PrintSaveFile()
    

    def _EditSaveFilePath(self) -> None : 
        """Asks the user for the POD device type, then asks the user for a new file name and path, \
        then sets the value to the POD devices.
        """
        deviceName = self._GetChosenDeviceType('What type of POD device do you want to change the filename for?')
        if(deviceName in self._Setup_PodDevices) :
            self._Setup_PodDevices[deviceName].SetupFileName()
        else : 
            print('[!] '+deviceName+' is not available.')


    def _EditCheckConnect(self) -> None :
        """Displays the POD devices parameters, asks the user to edit the device, and then reconnects \
        the device for each POD device type. 
        """
        deviceName = self._GetChosenDeviceType('What type of POD device do you want to edit?')
        # edit device if available 
        if(deviceName in self._Setup_PodDevices) :
            self._Setup_PodDevices[deviceName].DisplayPODdeviceParameters()
            self._Setup_PodDevices[deviceName]._EditParams()
            self._Setup_PodDevices[deviceName].ValidateParams()
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
            self._Setup_PodDevices[deviceName].AddPODdevice()
            self._Setup_PodDevices[deviceName].ValidateParams()
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
            'import Morelia\n' +
            'import Setup\n' + 
            'saveFileDicts = ' + str(self.GetSaveFileNames()) + '\n' + 
            'podParametersDict = ' + str(self.GetPODparametersInit())  + '\n' + 
            'go = Setup.SetupAllDevices.SetupAll(saveFileDicts, podParametersDict)'  + '\n' + 
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
            params = SetupAll._AskUserForDevices()
        else:
            params = podParametersDict
        # validation 
        self._Set_Setup_PodDevices(params)
        self._CheckForValidParams(params)
        # return valid dict 
        return(params)
        

    @staticmethod
    def _AskUserForDevices() : 
        """Asks the user what POD devices they want to use."""
        useParams = {}
        names = (Setup8206HR.GetDeviceName(), Setup8401HR.GetDeviceName(), Setup8229.GetDeviceName(), Setup8480SC.GetDeviceName(), Setup8274D.GetDeviceName()) # NOTE add all supported devices here 
        print('')
        for name in names:
            if(UserInput.AskYN('Will you be using any '+str(name)+' devices?')) : 
                useParams[name] = None
        # ask again if user responds No to all 
        if(len(useParams) == 0 ) : 
            print('[!] No POD devices selected. Please choose at least one device.')
            return(SetupAll._AskUserForDevices())
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
        goodKeys = (Setup8206HR.GetDeviceName(), Setup8401HR.GetDeviceName(), Setup8480SC.GetDeviceName(), Setup8229.GetDeviceName(), Setup8274D.GetDeviceName()) # NOTE add all supported devices here 
        for key,value in podParametersDict.items()  :
            # is the key a POD device name?
            if(key not in goodKeys) : # device not supported
                raise Exception('[!] Invalid device name in paramater dictionary: '+str(key)+'.')
            # is the value correct for the device?
            thisGood = self._Setup_PodDevices[key].AreDeviceParamsValid(value)
            allGood = allGood and thisGood # becomes false if any device is invalid 
        # should return true if no exceptions raised  
        return(allGood)


    def _Set_Setup_PodDevices(self, podParametersDict:dict[str,dict|None]) -> None : 
        """Sets the _Setup_PodDevices varaible to have keys as the POD device name and values \
        as the setup class.

        Args:
            podParametersDict (dict[str,dict | None]): Dictionary with keys as the device names \
                and values as None or the respective parameter dictionary.
        """
        # use select devices        
        name = Setup8206HR.GetDeviceName()
        if(name in podParametersDict ) : 
            self._Setup_PodDevices[name] = Setup8206HR()
        name = Setup8401HR.GetDeviceName()
        if(name in podParametersDict) : 
            self._Setup_PodDevices[name] = Setup8401HR()
        name = Setup8229.GetDeviceName()
        if(name in podParametersDict) : 
            self._Setup_PodDevices[name] = Setup8229()
        name = Setup8480SC.GetDeviceName()
        if(name in podParametersDict) : 
            self._Setup_PodDevices[name] = Setup8480SC()
        name = Setup8274D.GetDeviceName()
        if(name in podParametersDict) : 
            self._Setup_PodDevices[name] = Setup8274D()    
        # NOTE add all supported devices here 


    # ------------ STREAM ------------ 


    def _StreamAllDevices(self) -> None : 
        """Streams data from all the devices. User is asked to click enter to stop streaming. \
        Data is saved to file. Uses threading.
        """
        # start streaming from all devices 
        allThreads: dict[str, tuple[dict[int, Thread]] | dict[int, Thread]] = {}
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
            for streamThreads in allThreads.values() : # for each device type...
                if(isinstance(streamThreads,tuple)) : 
                    for threadDict in streamThreads :  # for (Bucket,BucketDrain) threads
                        for thread in threadDict.values() : # for each POD device...
                            thread.join()
                elif(isinstance(streamThreads,dict)) : 
                    for thread in streamThreads.values() : # for each POD device...
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