# venv 
import sys
import texttable
# local 
from SerialCommunication    import COM_io
from PodDevice_8206HR       import POD_8206HR

class Setup_8206HR : 
    
    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self, podParametersDict=None) :
        if(podParametersDict != None) : 
            self._podParametersDict = podParametersDict
        else:
            self._podParametersDict = {}


    # ============ PUBLIC METHODS ============      ========================================================================================================================

    def Run(self) :

        # TODO
        # DONE - get port from comport list
        # DONE - create pod device and connect to comport 
        # DONE - test connection using PING 
        # DONE - setup sample rate, LP1, LP2, LP3, gain
        # - setup file to save to
        # - start streaming
        # - continually get data
        # - make plot using data
        # - save data to file 
        # - ** make function that goes through setup and generates a dict to pass to Setup_8206HR __init__ to autosetup 


        # get setup parameters for all POD devices
        self._SetParam_allPODdevices()
        # display 
        self._DisplayPODdeviceParameters()
        # fix dict 
        self._ValidateParams()


    # ============ PROTECTED INSTANCE METHODS ============      ========================================================================================================================


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
        # ask if params are good or not
        validParams = Setup_8206HR._AskYN(question='Are the POD device parameters correct?')
        # edit if the parameters are not correct 
        if(not validParams) : 
            self._EditParams()
            # display 
            self._DisplayPODdeviceParameters()
            # prompt again
            self._ValidateParams()


    def _EditParams(self) :
        # chose device # to edit
        editThis = self._SelectPODdeviceFromDictToEdit()
        # get all port names except for device# to be edited
        forbiddenNames  = [x['Port'] for x in self._podParametersDict.values() if self._podParametersDict[editThis]['Port'] != x['Port']]
        # edit device
        print('\n-- Device #'+str(editThis+1)+' --\n')
        self._podParametersDict[editThis] = Setup_8206HR._GetParam_onePODdevice(forbiddenNames)
    
            
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


    # ============ PROTECTED STATIC METHODS ============      ========================================================================================================================


    # ------------ PARAMS ------------


    @staticmethod
    def _GetParam_onePODdevice(forbiddenNames) : 
        return({
                'Port'          : Setup_8206HR._ChoosePort(forbiddenNames), # isolate 'COM#' from full port name
                'Baud Rate'     : Setup_8206HR._ChooseBaudrate(),
                'Sample Rate'   : Setup_8206HR._ChooseSampleRate(),
                'Low Pass'      : Setup_8206HR._ChooseLowpass()
            })


    

    # ------------ CONNECT PORT ------------

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


    @staticmethod
    def _GetPortsList(forbidden=[]) : 
        # get port list 
        portListAll = COM_io.GetCOMportsList()
        # remove forbidden ports 
        portList = [x for x in portListAll if x not in forbidden]
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


    @staticmethod
    def _TestConnection(pod):
        # connection successful if write and read match 
        if(not pod.WritePacket('PING') == pod.ReadPODpacket()):
            raise Exception('[!] Connection failed. ')

    # ------------ DEVICE SETTINGS ------------
    
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
