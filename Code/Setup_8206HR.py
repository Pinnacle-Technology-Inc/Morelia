import sys

from SerialCommunication    import COM_io
from PodDevice_8206HR       import POD_8206HR

class Setup_8206HR : 
    
    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self) :
        # initialize 
        self._podDevices = [None]


    # ============ PUBLIC METHODS ============      ========================================================================================================================

    def Run(self) :

        # TODO
        # DONE - get port from comport list
        # DONE - create pod device and connect to comport 
        # DONE - test connection using PING 
        # - setup sample rate, LP1, LP2, LP3, gain
        # - setup file to save to
        # - start streaming
        # - continually get data
        # - make plot using data
        # - save data to file 
        # - ** make function that goes through setup and generates a dict to pass to Setup_8206HR __init__ to autosetup 

        self._SetupPODdevices()

        
        
    def _SetupPODdevices(self) : 
        # get the number of devices 
        numDevices = self._SetNumberOfDevices()

        # initialize lists 
        portNames = [None] * numDevices
        self._podDevices = [None] * numDevices

        # setup each POD device 
        i=0
        while(i < numDevices) : 
            # current index 
            print('\n-- Device #'+str(i+1)+' --\n')

            # get name of port
            portNames[i] = self._ChoosePort(forbidden=portNames)
            port = portNames[i].split(' ')[0] # isolate 'COM#' from full port name 

            # get baud rate 
            baudrate = self._ChooseBaudrate()

            # create POD device 
            try :
                # create POD device
                self._podDevices[i] = POD_8206HR(port=port, baudrate=baudrate)
                # ping to test connection 
                self._TestConnection(self._podDevices[i])
                print('Successfully connected '+port+' to Device #'+str(i+1)+'.\n')
            except :
                # fail message 
                print('[!] Failed to connect '+port+' to Device #'+str(i+1)+'. Try again.')
                # reset values 
                portNames[i] = None
                self._podDevices[i] = None
                # retry 
                continue

            # setup device 
            self._ChooseSampleRate(self._podDevices[i])
            self._ChooseLowpass(self._podDevices[i])

            # move to next device 
            i+=1
    # ============ PROTECTED METHODS ============      ========================================================================================================================


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
    def _ChooseSampleRate(pod):
        try : 
            # get sample rate from user 
            sampleRate = int(input('Sample rate (Hz): '))
        except : 
            # if bad input, start over 
            print('[!] Please enter an integer number.')
            return(Setup_8206HR._ChooseSampleRate(pod))

        # check for valid input
        if(sampleRate<100 or sampleRate>2000) : 
            print('[!] Sample rate must be between 100-2000.')
            return(Setup_8206HR._ChooseSampleRate(pod))

        # write sample rate to device 
        w = Setup_8206HR._WritePacket_Try(pod=pod, cmd='SET SAMPLE RATE', payload=sampleRate)


    @staticmethod
    def _ChooseLowpass(pod):
        # 0 = EEG1, 1 = EEG2, 2 = EEG3/EMG
        for eeg in range(3) : 
            Setup_8206HR._ChooseLowpassForEEG(eeg, pod)

    @staticmethod
    def _ChooseLowpassForEEG(eeg, pod):
        try : 
            # get lowpass from user 
            lowpass = int(input('Lowpass (Hz) for EEG'+str(eeg)+': '))
        except : 
            # if bad input, start over 
            print('[!] Please enter an integer number.')
            return(Setup_8206HR._ChooseLowpassForEEG(eeg, pod))

        # check for valid input
        if(lowpass<11 or lowpass>500) : 
            print('[!] Sample rate must be between 11-500 Hz.')
            return(Setup_8206HR._ChooseSampleRate(pod))

        # write lowpass for EEG# to device 
        w = Setup_8206HR._WritePacket_Try(pod=pod, cmd='SET LOWPASS', payload=(eeg, lowpass))


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