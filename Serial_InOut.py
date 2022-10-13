import serial.tools.list_ports

# read and write to serial COM ports 
class COM_io : 

    # ====== GLOBAL VARIABLES ======

    __serialInst = serial.Serial()

    # ====== STATIC METHODS ======

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

    @staticmethod
    def HexStrToByteArray(hexStr) :
        # convert a string of hex values to a byte array
        return(bytearray.fromhex(hexStr))

    # ====== DUNDER METHODS ======

    def __init__(self, port, baudrate=9600) :
        # open port  
        self.OpenSerialPort(port, baudrate=baudrate)

    def __del__(self):
        # close port 
        self.CloseSerialPort()

    # ====== PRIVATE METHODS ======

    def __BuildPortName(self, port) :   # private 
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

    # ====== PUBLIC METHODS ======

    # ----- BOOL CHECKS -----

    def IsSerialOpen(self) : 
        # true if serial port is open, false otherwise 
        return(self.__serialInst.isOpen())

    def IsSerialClosed(self) :
        # true if serial port is closed, false otherwise 
        return(not self.IsSerialOpen())

    # ----- SERIAL MANAGEMENT -----

    def CloseSerialPort(self):
        # close port if open 
        if(self.IsSerialOpen()) :
            self.__serialInst.close()

    def OpenSerialPort(self, port, baudrate=9600) : 
        # close current port if it is open
        if(self.IsSerialOpen()) : 
            self.CloseSerialPort()
        # get name 
        name = self.__BuildPortName(port)
        # if the 'Name' is not None
        if(name) : 
            # initialize and open serial port 
            self.__serialInst.baudrate = baudrate
            self.__serialInst.port = name
            self.__serialInst.open()
        else : 
            # throw an error 
            raise Exception('Port does not exist.')

    # ----- GETTERS -----

    def GetPortName(self) : 
        # return the port name if a port is open
        if(self.IsSerialOpen()) : 
            return(self.__serialInst.name) 
        # otherwise return nothing
        else :
            return(None)

    # ----- INPUT/OUTPUT -----

    def Read(self, numBytes):
        # do not continue of serial is not open 
        if(self.IsSerialClosed()) :
            return(None)
        # wait until port is in waiting, then read 
        while True :
            if self.__serialInst.in_waiting : 
                # read packet
                return(self.__serialInst.read(numBytes) )

    def ReadLine(self):
        # do not continue of serial is not open 
        if(self.IsSerialClosed()) :
            return(None)
        # wait until port is in waiting, then read line 
        while True :
            if self.__serialInst.in_waiting : 
                # read packet up to  and including newline ('\n')
                return(self.__serialInst.readline())
    
    def ReadUntil(self, eol) :
        # do not continue of serial is not open 
        if(self.IsSerialClosed()) :
            return(None)
        # wait until port is in waiting, then read 
        while True :
            if self.__serialInst.in_waiting : 
                # read packet until end of line (eol) character 
                return(self.__serialInst.read_until(eol) )

    def Write(self, message) : 
        # write message to open port 
        if(self.IsSerialOpen()) : 
            self.__serialInst.write(message)