import serial.tools.list_ports

class COM_io : 

    # class variables 
    serialInst = serial.Serial()

    @staticmethod
    def GetCOMportsList() : 
        # get all COM ports in use
        allPorts = serial.tools.list_ports.comports()
        # convert COM ports to string list 
        portList = []
        for port in allPorts:
            portList.append(str(port))
            print(str(port))
        # end
        return(portList)

    def __init__(self, port, baudrate=9600) :
        # open port  
        self.OpenSerialPort(port, baudrate=baudrate)

    def __del__(self):
        # close port 
        self.CloseSerialPort()

    def IsSerialOpen(self) : 
        # true if serial port is open, false otherwise 
        return(self.serialInst.isOpen())

    def IsSerialClosed(self) :
        # true if serial port is closed, false otherwise 
        return(not self.IsSerialOpen())

    def CloseSerialPort(self):
        # close port if open 
        if(self.IsSerialOpen()) :
            self.serialInst.close()

    def OpenSerialPort(self, port, baudrate=9600) : 
        # close current port if it is open
        if(self.IsSerialOpen()) : 
            self.CloseSerialPort()
        # get name 
        name = self.BuildPortName(port)
        # if the 'Name' is not None
        if(name) : 
            # initialize and open serial port 
            self.serialInst.baudrate = baudrate
            self.serialInst.port = name
            self.serialInst.open()
        else : 
            # throw an error 
            raise Exception('Port does not exist.')

    def BuildPortName(self, port) : 
        name = None
        # is 'port' the port number? 
        if (isinstance(port, int)) : 
            # build port name 
            name = 'COM' + str(port)
        elif (isinstance(port, str)): 
            # is 'port' the port name or just the number?
            if port.startswith('COM'):
                # assume that 'port' is the full name  
                name = port
            else : 
                # assume that 'port' is just the number 
                name = 'COM' + port
        # end 
        return(name)

    def GetPortName(self) : 
        # return the port name if a port is open
        if(self.IsSerialOpen()) : 
            return(self.serialInst.name) 
        # otherwise return nothing
        else :
            return(None)

    def ReadLine(self):
        # do not continue of serial is not open 
        if(self.IsSerialClosed()) :
            return(None)
        # wait until port is in waiting, then read line 
        while True :
            if self.serialInst.in_waiting : 
                # read packet up to  and including newline ('\n')
                return(self.serialInst.readline())
    

    def ReadNow(self, numBytes) : 
        # do not continue of serial is not open 
        if(self.IsSerialClosed()) :
            return(None)
        # get bytes if in waiting 
        if self.serialInst.in_waiting : 
            # read packet
            return(self.serialInst.read(numBytes) )
        # else return None 
        return(None)

    def Read(self, numBytes):
        # do not continue of serial is not open 
        if(self.IsSerialClosed()) :
            return(None)
        # wait until port is in waiting, then read 
        while True :
            if self.serialInst.in_waiting : 
                # read packet
                return(self.serialInst.read(numBytes) )

    def Write(self, message) : 
        if(self.IsSerialOpen()) : 
            self.serialInst.write(message)