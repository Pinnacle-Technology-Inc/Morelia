import serial

# port names
# these depend on the board I think?
portName_read  = 'COM3'
portName_write = 'COM4'

# store current port name (if you make this a class later, this is initialized)
port = portName_read

# open serial port 
ser = serial.Serial(port)

# read from the board
def Read():
    pass

# write a message to the board
def Write(msg):
    pass

# write ping command to device, and device shoudld return the same string
def Ping():
    
    # basic pod ping command: STX 0 0 0 2 3 D ETX
    # Sending that hex string to a pod device should cause it to return the same string
    STX   = "0x02"          # indicates the start of a packet
    ZERO  = "0x30"          # vvv
    TWO   = "0x32"          # 0002 is the command number in ASCII numerals
    THREE = "0x33"          # vvv
    D     = "0x44"          # 3D is the checksum value, in ASCII numerals
    ETX   = "0x03"          # indicates the end of a packet
    # Because the packets are all ASCII character encoded, there should never be a 0x02 or 0x03 

    pass 