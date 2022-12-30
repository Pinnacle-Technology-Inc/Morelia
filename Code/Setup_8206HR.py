# venv 
import sys
import texttable
# local 
from SerialCommunication    import COM_io
from PodDevice_8206HR       import POD_8206HR

class Setup_8206HR : 
    
    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self, podParametersDict=None) :
        # initialize dictionary of POD device parameters
        if(podParametersDict != None) : 
            self._podParametersDict = podParametersDict
            self._DisplayPODdeviceParameters()
        else:
            self._podParametersDict = {}

        # initialize dictionary of POD devices
        self._podDevices = {}

        # initialize options --> NOTE if you change this, be sure to update _DoOption()
        self._options = {
            1 : 'Print dictionary of POD devices.',
            2 : 'Show table of POD devices.',
            3 : 'Edit POD device settings.',
            4 : 'Connect a new POD device.',
            5 : 'Start Streaming.',
            6 : 'Quit.'
        }


    # ============ PUBLIC METHODS ============      ========================================================================================================================

    def Run(self) :

        #   TODO
        # DONE - get port from comport list
        # DONE - create pod device and connect to comport 
        # DONE - setup sample rate, LP1, LP2, LP3
        # - setup file to save to
        # - start streaming
        # - continually get data
        # - make plot using data
        # - save data to file 


        # == setup 
        # ask user for parameters if they were not initialized 
        if(len(self._podParametersDict) == 0) : 
            # get setup parameters for all POD devices
            self._SetParam_allPODdevices()
            # display parameters and allow user to edit them
            self._ValidateParams()
        # connect and initialize all POD devices
        self._ConnectAllPODdevices()

        # == option loop 
        # init looping condition 
        choice = 0
        quit = list(self._options.keys())[list(self._options.values()).index('Quit.')] # abstracted way to get dict key for 'Quit.'
        # keep prompting user until user wants to quit
        while(choice != quit) :
            self._PrintOptions()
            choice = self._AskOption()
            self._DoOption(choice)

    # ------------ WORKING ------------

    def _StreamAll() : 
        pass

    # ============ PROTECTED INSTANCE METHODS ============      ========================================================================================================================

    
    # ------------ SETUP ------------


    def _SetParam_allPODdevices(self) :
        # get the number of devices 
        numDevices = self._SetNumberOfDevices()
        # initialize 
        portNames = [None] * numDevices
        podDict = {}
        # get information for each POD device 
        for i in range(numDevices) : 
            # current index 
            print('\n-- Device #'+str(i+1)+' --\n')
            # get parameters
            onePodDict = Setup_8206HR._GetParam_onePODdevice(portNames)
            # update lists 
            portNames[i] = onePodDict['Port']
            podDict[i] = onePodDict
        # save dict containing information to setup all POD devices
        self._podParametersDict = podDict


    def _DisplayPODdeviceParameters(self) : 
        # print title 
        print('\nParameters for all POD Devices:')
        # setup table 
        tab = texttable.Texttable()
        # write column names
        tab.header(['Device #','Port','Baud Rate','Sample Rate (Hz)','EEG1 Low Pass (Hz)','EEG2 Low Pass (Hz)','EEG3/EMG Low Pass (Hz)'])
        # write rows
        for key,val in self._podParametersDict.items() :
            tab.add_row([key+1, val['Port'], val['Baud Rate'], val['Sample Rate'], val['Low Pass']['EEG1'], val['Low Pass']['EEG2'], val['Low Pass']['EEG3/EMG'],])
        # show table 
        print(tab.draw())
        
    
    def _ValidateParams(self) : 
        # display all pod devices and parameters
        self._DisplayPODdeviceParameters()
        # ask if params are good or not
        validParams = Setup_8206HR._AskYN(question='Are the POD device parameters correct?')
        # edit if the parameters are not correct 
        if(not validParams) : 
            # edit the parameters table
            self._EditParams()
            # prompt again
            self._ValidateParams()


    def _EditParams(self) :
        # chose device # to edit
        editThis = self._SelectPODdeviceFromDictToEdit()
        # get all port names except for device# to be edited
        forbiddenNames = self._GetForbiddenNames(exclude=self._podParametersDict[editThis]['Port'])
        # edit device
        print('\n-- Device #'+str(editThis+1)+' --\n')
        self._podParametersDict[editThis] = Setup_8206HR._GetParam_onePODdevice(forbiddenNames)
    

    def _GetForbiddenNames(self, exclude=None):
        if(exclude == None) : 
            portNames = [x['Port'] for x in self._podParametersDict.values()]
        else :
            portNames = [x['Port'] for x in self._podParametersDict.values() if exclude != x['Port']]
        return(portNames)
            

    def _SelectPODdeviceFromDictToEdit(self):
        try:
            # get pod device number from user 
            podKey = ( int(input('Edit POD Device #: ')) - 1 )
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
            self._podDevices[deviceNum].WritePacket('SET SAMPLE RATE', deviceParams['Sample Rate'])
            self._podDevices[deviceNum].WritePacket('SET LOWPASS', (0, deviceParams['Low Pass']['EEG1']))
            self._podDevices[deviceNum].WritePacket('SET LOWPASS', (1, deviceParams['Low Pass']['EEG2']))
            self._podDevices[deviceNum].WritePacket('SET LOWPASS', (2, deviceParams['Low Pass']['EEG3/EMG']))
            # done 
            print('Successfully connected POD device #'+str(deviceNum+1)+' to '+port+'.')
        except : 
            print('Failed to connect POD device #'+str(deviceNum+1)+' to '+port+'.')
            sys.exit('[!] Fatal error... ending program.')


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
            print('\nDictionary of current POD parameter set:')
            print(self._podParametersDict)
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
            nextNum = max(self._podParametersDict.keys())+1
            print('\n-- Device #'+str(nextNum+1)+' --\n')
            self._podParametersDict[nextNum] = self._GetParam_onePODdevice(self._GetForbiddenNames())
            self._ValidateParams()
            self._ConnectAllPODdevices()

         # Start Streaming.
        elif(choice == 5): 
            pass

        # Quit.
        else:               
            print('\nQuitting...\n')


    # ============ PROTECTED STATIC METHODS ============      ========================================================================================================================


    # ------------ DEVICE SETUP ------------


    @staticmethod
    def _GetParam_onePODdevice(forbiddenNames) : 
        return({
                'Port'          : Setup_8206HR._ChoosePort(forbiddenNames),
                'Baud Rate'     : Setup_8206HR._ChooseBaudrate(),
                'Sample Rate'   : Setup_8206HR._ChooseSampleRate(),
                'Low Pass'      : Setup_8206HR._ChooseLowpass()
            })
    

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


    # ------------ PORT SETTINGS ------------


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


    # ------------ POD DEVICE SETTINGS ------------
    

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
        

    # ------------ READ/WRITE ------------


    @staticmethod
    def _WritePacket_Try(pod, cmd, payload=None, quitIfFail=True):
        try:
            w = pod.WritePacket(cmd=cmd, payload=payload)
            return(w)
        except : 
            print('[!] Connection error: could not write to POD device.')
            if(quitIfFail) :
                sys.exit('[!!!] Fatal Error: closing program.')


    @staticmethod
    def _TestConnection(pod):
        # connection successful if write and read match 
        if(pod.WritePacket('PING') == pod.ReadPODpacket()):
            return(True)
        else:
            return(False)


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

    