import time 

from SerialCommunication    import COM_io
from PodDevice_8206HR       import POD_8206HR

class Setup_8206HR : 
    
    # ============ PUBLIC METHODS ============      ========================================================================================================================

    def Run(self) :

        # TODO
        # - get port from comport list
        # - create pod device and connect to comport 
        # - test connection using PING 
        # - setup sample rate, LP1, LP2, LP3, gain
        # - setup file to save to
        # - start streaming
        # - continually get data
        # - make plot using data
        # - save data to file 



        # get the number of devices 
        numDevices = self.SetNumberOfDevices()

        # initialize lists 
        portNames = [None] * numDevices
        podDevices = [None] * numDevices

        # setup each POD device 
        i=0
        while(i < numDevices) : 
            # current index 
            print('\n- Device #'+str(i+1))

            # get name of port
            portNames[i] = self.ChoosePort(forbidden=portNames)
            port = portNames[i].split(' ')[0] # isolate 'COM#' from full port name 

            # get baud rate 
            baudrate = self.ChooseBaudrate(default=False)

            # setup device 
            try :
                # create POD device
                podDevices[i] = POD_8206HR(port=port, baudrate=baudrate)
                # ping to test connection 
                self.TestConnection(podDevices[i])
                print('Successfully connected '+port+' to Device #'+str(i+1)+'.')
            except :
                # fail message 
                print('[!] Failed to connect '+port+' to Device #'+str(i+1)+'. Try again.')
                # reset values 
                portNames[i] = None
                podDevices[i] = None
                # retry 
                continue

            # move to next device 
            i+=1
        


    # ============ PRIVATE METHODS ============      ========================================================================================================================

    def SetNumberOfDevices(self) : 
        try : 
            # request user imput
            n = int(input('How many POD devices do you want to use?: '))
            # number must be positive
            if(n<=0):
                print('[!] Number must be greater than zero.')
                return(self.SetNumberOfDevices())
            # return number of POD devices 
            return(n)
        except : 
            # print error and start over
            print('[!] Please enter an integer number.')
            return(self.SetNumberOfDevices())


    def GetPortsList(self,forbidden=[]) : 
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


    def ChoosePort(self, forbidden=[]) : 
        # get ports
        portList = self.GetPortsList(forbidden)
        print('Available COM Ports:', portList)
        # request port from user
        choice = input('Select port: COM')
        # search for port in list
        for port in portList:
            if port.startswith('COM'+choice):
                return(port)
        # if return condition not reached...
        print('[!] COM'+choice+' does not exist. Try again.')
        return(self.ChoosePort(forbidden))

    
    def ChooseBaudrate(self, default=False):
        # return default
        if(default):
            return(9600)
        # else use user input 
        try : 
            # request user imput
            n = int(input('Set baud rate: '))
            # number must be positive
            if(n<=0):
                print('[!] Number must be greater than zero.')
                return(self.ChooseBaudrate(default))
            # return baudrate
            return(n)
        except : 
            # print error and start over
            print('[!] Please enter an integer number.')
            return(self.ChooseBaudrate(default))


    def TestConnection(self, pod):
        # write ping, excpect to read ping 
        w = pod.WritePacket('PING')
        r = pod.ReadPODpacket()
        # connection successful if write and read match 
        if(w==r):
            return(True)
        else:
            raise Exception('[!] Connection failed. ')