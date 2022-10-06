from struct import pack
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

    def CloseSerialPort(self):
        # close port if open 
        if(self.serialInst.isOpen()) :
            self.serialInst.close()

    def OpenSerialPort(self, port, baudrate=9600) : 
        # close current port if it is open
        if(self.serialInst.isOpen()) : 
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
        if(self.serialInst.isOpen()) : 
            return(self.serialInst.name) 
        # otherwise return nothing
        else :
            return(None)

    def ReadLineNow(self) : 
        # do not continue of serial is not open 
        if(self.serialInst.isOpen() == False) :
            return(None)
        # get packet if in waiting 
        if self.serialInst.in_waiting : 
            # read packet up to  and including newline ('\n')
            return(self.serialInst.readline() )
        # else return None 
        return(None)

    def ReadLineWhenReady(self):
        while True :
            # get packiet 
            packet = self.ReadLineNow()
            # return when packet is not None 
            if(packet) :
                return(packet) 
    

# =================== NOTE ===================

# # write a message to the board
# def Write(msg):
#     pass

# # write ping command to device, and device shoudld return the same string
# def Ping():
    
#     # basic pod ping command: STX 0 0 0 2 3 D ETX
#     # Sending that hex string to a pod device should cause it to return the same string
#     STX   = "0x02"          # indicates the start of a packet
#     ZERO  = "0x30"          # vvv
#     TWO   = "0x32"          # 0002 is the command number in ASCII numerals
#     THREE = "0x33"          # vvv
#     D     = "0x44"          # 3D is the checksum value, in ASCII numerals
#     ETX   = "0x03"          # indicates the end of a packet
#     # Because the packets are all ASCII character encoded, there should never be a 0x02 or 0x03 
#     pass 