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
        print('\n')

        # get port name of each device 
        portNames = [''] * numDevices
        for i in range(numDevices) : 
            print('- Device #',i+1)
            portNames[i] = self.ChoosePort(forbidden=portNames)
            print('\n')
        print('Selected Ports:', portNames)

        

    # ============ PRIVATE METHODS ============      ========================================================================================================================

    def SetNumberOfDevices(self) : 
        try : 
            # request user imput
            n = int(input('How many POD devices do you want to use?: '))
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