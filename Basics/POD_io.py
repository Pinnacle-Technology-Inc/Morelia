import serial.tools.list_ports

# make class that
# 1. shows comports (static method)
# 2. opens COM (constructor)
# 3. reads from COM
# 4. write to COM

class COM_io : 

    # class variables 
    serialInst = serial.Serial()

    def __init__(self, port, baudrate=96000) :
        # open port  
        self.OpenSerialPort(port, baudrate=baudrate)

    def CloseSerialPort(self):
        self.serialInst.close()

    def OpenSerialPort(self, port, baudrate=96000) : 
        # close current port if it is open
        if(self.serialInst.isOpen()) : 
            self.CloseSerialPort()
        # get name 
        portName = self.BuildPortName(port)
        # if the 'portName' is not None
        if(portName) : 
            # initialize and open serial port 
            self.serialInst.baudrate = baudrate
            self.serialInst.port = portName
            self.serialInst.open()
        else : 
            # throw an error 
            raise Exception('Port does not exist.')

    def BuildPortName(self, port) : 
        portName = None
        # is 'port' the port number? 
        if (isinstance(port, int)) : 
            # build port name 
            portName = 'COM' + str(port)
        elif (isinstance(port, str)): 
            # is 'port' the port name or just the number?
            if port.startswith('COM'):
                # assume that 'port' is the full name  
                portName = port
            else : 
                # assume that 'port' is just the number 
                portName = 'COM' + port
        # end 
        return(portName)

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

# =================== NOTE ===================

# # read from the board
# def Read():
#     pass

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