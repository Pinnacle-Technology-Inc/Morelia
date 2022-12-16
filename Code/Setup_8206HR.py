import time 

from SerialCommunication    import COM_io
from PodDevice_8206HR       import POD_8206HR

class Setup_8206HR : 
    
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



        # get the number of devices 
        numDevices = self._SetNumberOfDevices()

        # initialize lists 
        portNames = [None] * numDevices
        podDevices = [None] * numDevices

        # setup each POD device 
        i=0
        while(i < numDevices) : 
            # current index 
            print('\n- Device #'+str(i+1))

            # get name of port
            portNames[i] = self._ChoosePort(forbidden=portNames)
            port = portNames[i].split(' ')[0] # isolate 'COM#' from full port name 

            # get baud rate 
            baudrate = self._ChooseBaudrate()

            # create POD device 
            try :
                # create POD device
                podDevices[i] = POD_8206HR(port=port, baudrate=baudrate)
                # ping to test connection 
                self._TestConnection(podDevices[i])
                print('Successfully connected '+port+' to Device #'+str(i+1)+'.')
            except :
                # fail message 
                print('[!] Failed to connect '+port+' to Device #'+str(i+1)+'. Try again.')
                # reset values 
                portNames[i] = None
                podDevices[i] = None
                # retry 
                continue

            # setup device 
            self._ChooseSampleRate(podDevices[i])

            # move to next device 
            i+=1
        


    # ============ PROTECTED METHODS ============      ========================================================================================================================

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

    
    @staticmethod
    def _ChooseSampleRate(pod):
        try : 
            # get sample rate from user 
            sampleRate = int(input('Sample rate: '))
        except : 
            # if bad input, start over 
            print('[!] Please enter an integer number.')
            return(Setup_8206HR._ChooseSampleRate(pod))

        # check for valid input
        if(sampleRate<100 or sampleRate>2000) : 
            print('[!] Sample rate must be between 100-2000.')
            return(Setup_8206HR._ChooseSampleRate(pod))

        # write sample rate to device 
        w = pod.WritePacket('SET SAMPLE RATE', sampleRate)


    @staticmethod
    def _ChooseLowpassForEEG(pod):
        # 0 = EEG1, 1 = EEG2, 2 = EEG3/EMG
        for eeg in range(3) : 
            Setup_8206HR._ChooseLowpassForEEG(eeg, pod)

    @staticmethod
    def _ChooseLowpassForEEG(eeg, pod):
        pass
