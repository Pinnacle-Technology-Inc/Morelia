# venv 
import os
import sys
import texttable
# local 
from SerialCommunication    import COM_io
from PodDevice_8206HR       import POD_8206HR

# TODO
# DONE - get port from comport list
# DONE - create pod device and connect to comport 
# DONE - setup sample rate, LP1, LP2, LP3
# - setup TTL stuff ???
# DONE - setup file to save to
# DONE - start streaming
# DONE- continually get data
# - stop streaming 
# - make plot using data
# DONE - save data to file 

class Setup_8206HR : 
    

    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self, saveFile=None, podParametersDict=None) :
        # initialize class instance variables
        self._podDevices = {}
        self._podParametersDict = {}
        self._saveFileName = ''
        self._saveFile = None 
        self._options = { # NOTE if you change this, be sure to update _DoOption()
            1 : 'Print dictionary of POD devices.',
            2 : 'Show table of POD devices.',
            3 : 'Edit POD device settings.',
            4 : 'Connect a new POD device.',
            5 : 'Setup save file for streaming.',
            6 : 'Print save file name and path.',
            7 : 'Start Streaming.',
            8 : 'Quit.'
        }
        # setup 
        self.SetupPODparameters(podParametersDict)
        self.SetupSaveFile(saveFile)


    def __del__(self):
        # delete all POD objects 
        self._DisconnectAllPODdevices
        # close file
        self._CloseSaveFile()


    # ============ PUBLIC METHODS ============      ========================================================================================================================


    def SetupPODparameters(self, podParametersDict):
        # get dictionary of POD device parameters
        if(podParametersDict==None):
            self._SetParam_allPODdevices()  # get setup parameters for all POD devices
            self._ValidateParams()          # display parameters and allow user to edit them
        else:
            self._podParametersDict = podParametersDict
            self._DisplayPODdeviceParameters()  # display table of all POD devies and parameters
        # connect and initialize all POD devices
        self._ConnectAllPODdevices()


    def SetupSaveFile(self, saveFile):
        # initialize file name and path 
        if(saveFile == None) :
            self._saveFileName = self._GetFilePath()
        else:
            self._saveFileName = saveFile


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
    

    # ------------ STREAM ------------ TODO move this 


    def _Stream(self) : 
        print('\nStreaming data from all POD devices...')
        # open file
        self._OpenSaveFile()
        self._WriteHeaderToFile()
        # read from POD 
        self._StartStream()
        for i in range (100) : 
            self._ReadAll()
        # stop streaming 
        self._StopStream()
        self._CloseSaveFile()

        # TODO use multithreading to handle streaming!
        # - make a thread for each POD device. 
        #       These threads should write STREAM ON to their device, 
        #       then continually read until a STREAM OFF packet is read. 
        #       each thread should write to its own file 
        #           use the given path but add the device number to the filename: path\filename_<DEVICE#>.ext
        #           alternativly, ask user for a path and filename when setting up the device params
        # - make a thread that asks for user input
        #       ask user "press any key to stop streaming: ". 
        #       when the user gives an input, write STREAM OFF to each POD device. 
        #       print "finishing up..." until the POD device threads are done reading 
        # - print time from start to stop read 
        # TODO convert ch value into volts 


    
    def _StartStream(self):
        for pod in self._podDevices.values() : 
            # write then read once 
            r = pod.WriteRead(cmd='STREAM', payload=1) 
        return(r)   # all read packes should be same 

    def _StopStream(self):
        for pod in self._podDevices.values() : 
            # write only 
            w = pod.WritePacket(cmd='STREAM', payload=0)
        return(w)   # all write packets should be same 

    def _ReadAll(self) : 
        # read binary packet from each POD device 
        for devNum,pod in self._podDevices.items() :
            r = pod.TranslatePODpacket(pod.ReadPODpacket())
            # TODO convert to volts 
            self._WriteDataToFile(devNum, r)


    # ------------ DEVICES ------------


    @staticmethod
    def _SetNumberOfDevices() : 
        try : 
            # request user imput
            n = int(input('How many POD devices do you want to use?: '))
            # number must be positive
            if(n<=0):
                print('[!] Number must be greater than zero.')
                return(Setup_8206HR._SetNumberOfDevices())
            # return number of POD devices 
            return(n)
        except : 
            # print error and start over
            print('[!] Please enter an integer number.')
            return(Setup_8206HR._SetNumberOfDevices())
    

    def _DisconnectAllPODdevices(self) :
        for k in list(self._podDevices.keys()) : 
            pod = self._podDevices.pop(k)
            del pod 


    def _ConnectAllPODdevices(self) : 
        # delete existing 
        self._DisconnectAllPODdevices()
        # connect new devices
        print('\nConnecting POD devices...')
        # setup each POD device
        for key,val in self._podParametersDict.items():
           self._ConnectPODdevice(key,val)
                

    def _ConnectPODdevice(self, deviceNum, deviceParams) : 
        try : 
            # get port name 
            port = deviceParams['Port'].split(' ')[0] # isolate COM# from rest of string
            # create POD device 
            self._podDevices[deviceNum] = POD_8206HR(port, deviceParams['Baud Rate'])
            # write setup parameters
            self._podDevices[deviceNum].WriteRead('SET SAMPLE RATE', deviceParams['Sample Rate'])
            self._podDevices[deviceNum].WriteRead('SET LOWPASS', (0, deviceParams['Low Pass']['EEG1']))
            self._podDevices[deviceNum].WriteRead('SET LOWPASS', (1, deviceParams['Low Pass']['EEG2']))
            self._podDevices[deviceNum].WriteRead('SET LOWPASS', (2, deviceParams['Low Pass']['EEG3/EMG']))
            # done 
            print('Successfully connected POD device #'+str(deviceNum)+' to '+port+'.')
        except : 
            print('Failed to connect POD device #'+str(deviceNum)+' to '+port+'.')
            sys.exit('[!] Fatal error... ending program.')  # TODO find a better way to address error instead of crashing 


    def _AddPODdevice(self):
        nextNum = max(self._podParametersDict.keys())+1
        self._PrintDeviceNumber(nextNum)
        self._podParametersDict[nextNum] = self._GetParam_onePODdevice(self._GetForbiddenNames())


    # ------------ SETUP POD PARAMETERS ------------
    

    def _SetParam_allPODdevices(self) :
        # get the number of devices 
        numDevices = self._SetNumberOfDevices()
        # initialize 
        portNames = [None] * numDevices
        podDict = {}
        # get information for each POD device 
        for i in range(numDevices) : 
            # current index 
            self._PrintDeviceNumber(i+1)
            # get parameters
            onePodDict = Setup_8206HR._GetParam_onePODdevice(portNames)
            # update lists 
            portNames[i] = onePodDict['Port']
            podDict[i+1] = onePodDict
        # save dict containing information to setup all POD devices
        self._podParametersDict = podDict


    @staticmethod
    def _GetParam_onePODdevice(forbiddenNames) : 
        return({
                'Port'          : Setup_8206HR._ChoosePort(forbiddenNames),
                'Baud Rate'     : Setup_8206HR._ChooseBaudrate(),
                'Sample Rate'   : Setup_8206HR._ChooseSampleRate(),
                'Low Pass'      : Setup_8206HR._ChooseLowpass()
            })
        
    
    @staticmethod
    def _ChoosePort(forbidden=[]) : 
        # get ports
        portList = Setup_8206HR._GetPortsList(forbidden)
        print('Available COM Ports:', portList)
        # request port from user
        choice = input('Select port: COM')
        # choice cannot be an empty string
        if(choice == ''):
            print('[!] Please choose a COM port.')
            return(Setup_8206HR._ChoosePort(forbidden))
        else:
            # search for port in list
            for port in portList:
                if port.startswith('COM'+choice):
                    return(port)
            # if return condition not reached...
            print('[!] COM'+choice+' does not exist. Try again.')
            return(Setup_8206HR._ChoosePort(forbidden))


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
        

    @staticmethod
    def _ChooseBaudrate(useDefault=False, defaultValue=9600):
        # return default
        if(useDefault):
            return(defaultValue)
        # else use user input 
        try : 
            # request user imput
            n = int(input('Set baud rate: '))
            # number must be positive
            if(n<=0):
                print('[!] Number must be greater than zero.')
                return(Setup_8206HR._ChooseBaudrate(useDefault,defaultValue))
            # return baudrate
            return(n)
        except : 
            # print error and start over
            print('[!] Please enter an integer number.')
            return(Setup_8206HR._ChooseBaudrate(useDefault,defaultValue))
            

    @staticmethod
    def _ChooseSampleRate():
        try : 
            # get sample rate from user 
            sampleRate = int(input('Set sample rate (Hz): '))
        except : 
            # if bad input, start over 
            print('[!] Please enter an integer number.')
            return(Setup_8206HR._ChooseSampleRate())
        # check for valid input
        if(sampleRate<100 or sampleRate>2000) : 
            print('[!] Sample rate must be between 100-2000.')
            return(Setup_8206HR._ChooseSampleRate())
        # return sample rate
        return(sampleRate)
       

    @staticmethod
    def _ChooseLowpass():
        # get lowpass for all EEG
        return({
            'EEG1'      : Setup_8206HR._ChooseLowpassForEEG(0),
            'EEG2'      : Setup_8206HR._ChooseLowpassForEEG(1),
            'EEG3/EMG'  : Setup_8206HR._ChooseLowpassForEEG(2),
        })


    @staticmethod
    def _ChooseLowpassForEEG(eeg):
        try : 
            # get lowpass from user 
            lowpass = int(input('Set lowpass (Hz) for EEG'+str(eeg)+': '))
        except : 
            # if bad input, start over 
            print('[!] Please enter an integer number.')
            return(Setup_8206HR._ChooseLowpassForEEG(eeg))
        # check for valid input
        if(lowpass<11 or lowpass>500) : 
            print('[!] Sample rate must be between 11-500 Hz.')
            return(Setup_8206HR._ChooseLowpassForEEG(eeg))
        # return lowpass
        return(lowpass)


    # ------------ EDIT POD PARAMETERS ------------
    

    def _ValidateParams(self) : 
        # display all pod devices and parameters
        self._DisplayPODdeviceParameters()
        # ask if params are good or not
        validParams = Setup_8206HR._AskYN(question='Are the POD device parameters correct?')
        # edit if the parameters are not correct 
        if(not validParams) : 
            self._EditParams()
            self._ValidateParams()


    def _EditParams(self) :
        # chose device # to edit
        editThis = self._SelectPODdeviceFromDictToEdit()
        # get all port names except for device# to be edited
        forbiddenNames = self._GetForbiddenNames(exclude=self._podParametersDict[editThis]['Port'])
        # edit device
        self._PrintDeviceNumber(editThis)
        self._podParametersDict[editThis] = Setup_8206HR._GetParam_onePODdevice(forbiddenNames)


    def _SelectPODdeviceFromDictToEdit(self):
        try:
            # get pod device number from user 
            podKey = int(input('Edit POD Device #: '))
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


    def _GetForbiddenNames(self, exclude=None):
        if(exclude == None) : 
            portNames = [x['Port'] for x in self._podParametersDict.values()]
        else :
            portNames = [x['Port'] for x in self._podParametersDict.values() if exclude != x['Port']]
        return(portNames)


    # ------------ DISPLAY POD PARAMETERS ------------

    @staticmethod
    def _PrintDeviceNumber(num):
        print('\n-- Device #'+str(num)+' --\n')


    def _PrintPODdeviceParamDict(self):
        print('\nDictionary of current POD parameter set:\n'+str(self._podParametersDict))


    def _DisplayPODdeviceParameters(self) : 
        # print title 
        print('\nParameters for all POD Devices:')
        # setup table 
        tab = texttable.Texttable()
        # write column names
        tab.header(['Device #','Port','Baud Rate','Sample Rate (Hz)','EEG1 Low Pass (Hz)','EEG2 Low Pass (Hz)','EEG3/EMG Low Pass (Hz)'])
        # write rows
        for key,val in self._podParametersDict.items() :
            tab.add_row([key, val['Port'], val['Baud Rate'], val['Sample Rate'], val['Low Pass']['EEG1'], val['Low Pass']['EEG2'], val['Low Pass']['EEG3/EMG'],])
        # show table 
        print(tab.draw())
        
    
    # ------------ FILE HANDLING ------------


    def _PrintSaveFile(self):
        print('\nStreaming data will be saved to '+self._saveFileName)
 

    @staticmethod
    def _GetFilePath() : 
        # ask user for path 
        path = input('\nWhere would you like to save streaming data to?\nPath: ')
        # split into path/name and extension 
        name, ext = os.path.splitext(path)

        # if there is no extension , assume that a file name was not given and path ends with a directory 
        if(ext == '') : 
            # ask user for file name 
            fileName = Setup_8206HR._GetFileName()
            # check for slash 
            if( ('/' in name) and (not name.endswith('/')) )  :
                name = name+'/'
            elif(not name.endswith('\\')) : 
                name = name+'\\'
            # return complete path and filename 
            return(name+fileName)

        # prompt again if bad extension is given 
        elif(ext!='.csv' and ext!='.txt') : 
            print('[!] Filename must end in .csv or .txt.')
            return(Setup_8206HR._GetFilePath())

        # path is correct
        else :
            return(path)


    @staticmethod
    def _GetFileName():
        # ask user for file name 
        name, ext = os.path.splitext(input('File name: '))
        # default to csv if no extension is given
        if(ext=='') : ext='.csv'
        # check if extension is correct 
        if(ext!='.csv' and ext!='.txt') : 
            print('[!] Filename must end in .csv or .txt.')
            return(Setup_8206HR._GetFileName())
        # return file name with extension 
        return(name+ext)


    def _OpenSaveFile(self):
        # close if already open 
        if(self._IsSaveFileOpen()) : self._CloseSaveFile()
        # open file to write to 
        self._saveFile = open(self._saveFileName, 'w')


    def _CloseSaveFile(self):
        # close the open file 
        if(self._IsSaveFileOpen()) : 
            self._saveFile.close()
    

    def _IsSaveFileOpen(self):
        # check that file exists 
        if(self._saveFile == None) : return(False)
        # check if closed 
        else: return(not self._saveFile.closed)


    def _WriteHeaderToFile(self) : 
        if(self._IsSaveFileOpen()): 
            # write column names to file 
            self._saveFile.write('Device #,Packet #,TTL,ch0,ch1,ch2\n')


    def _WriteDataToFile(self, devNum, dataPacket):
        if(self._IsSaveFileOpen()): 
            # get useful data in list 
            data = [devNum, dataPacket['Packet #'], dataPacket['TTL'], dataPacket['Ch0'], dataPacket['Ch1'], dataPacket['Ch2']]
            # convert data into comma separated string
            line = ','.join(str(x) for x in data) + '\n'
            # write data to file 
            self._saveFile.write(line)


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


    def _DoOption(self, choice) : 
        # Print dictionary of POD devices.
        if  (choice == 1):
            self._PrintPODdeviceParamDict()
        # Show Current POD devices.
        elif(choice == 2):  
            self._DisplayPODdeviceParameters()
        # Edit POD device settings.
        elif(choice == 3):  
            self._DisplayPODdeviceParameters()
            self._EditParams()
            self._ValidateParams()
            self._ConnectAllPODdevices()
        # Add a POD device.
        elif(choice == 4):  
            self._AddPODdevice()
            self._ValidateParams()
            self._ConnectAllPODdevices()
        # Setup save file for streaming.
        elif(choice == 5): 
            self._saveFileName = self._GetFilePath()
        # Print save file name and path.
        elif(choice == 6): 
            self._PrintSaveFile()
        # Start Streaming.
        elif(choice == 7): 
            self._Stream()
        # Quit.
        else:               
            print('\nQuitting...\n')


    # ------------ HELPER ------------


    @staticmethod
    def _AskYN(question) : 
        response = input(str(question)+' (y/n): ')
        if(response=='y' or response=='Y' or response=='yes' or response=='Yes'):
            return(True)
        elif(response=='n' or response=='N' or response=='no' or response=='No'):
            return(False)
        else:
            print('[!] Please enter \'y\' or \'n\'.')
            return(Setup_8206HR._AskYN(question))

    