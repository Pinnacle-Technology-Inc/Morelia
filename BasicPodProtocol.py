from Serial_InOut import COM_io

class POD_Basics(COM_io) : 

    # ====== GLOBAL VARIABLES ======

    # command numbers 
    __COMMAND_NUMBERS = [0,1,2,3,4,5,6,7,8,9,10,11,12]

    # command names
    __COMMAND_NAMES = [
        'ACK',
        'NACK',
        'PING',
        'RESET',
        'ERROR',
        'STATUS',
        'STREAM',
        'BOOT',
        'TYPE',
        'ID'
        'SAMPLE RATE',
        'BINARY',
        'FIRMWARE VERSION'
    ]

    # command description 
    __COMMAND_DESCRIPTIONS = [
        '0 = ACK - Deprecated in favor of responding with the command number received',
        '1 = NACK - Used to indicate an unsupported command was received',
        '2 = PING - Basic ping command to check if a device is alive and communicating',
        '3 = RESET - Causes the device to reset.  Devices also send this command upon bootup',
        '4 = ERROR - Reports error codes; mostly unused',
        '5 = STATUS - Reports status codes; mostly unused',
        '6 = STREAM - Enables or disables streaming of binary packets on the device',
        '7 = BOOT - Instructs the device to enter bootload mode',
        '8 = TYPE - Gets the device type. Often unused due to USB descriptor duplicating this function',
        '9 = ID - ID number for the device. Often unused due to USB descriptor duplicating this function',
        '10 = SAMPLE RATE - Gets the sample rate of the device.  Often unused in favor of just setting it.',
        '11 = BINARY - Indicates a binary packet.  See Binary Packets below',
        '12 = FIRMWARE VERSION - Returns firmware version of the device'
    ]

    # binary flag 
    __allowBinaryPackets = False

    # ====== STATIC METHODS ======

    @staticmethod
    def GetCommandNumbers():
        return(POD_Basics.__COMMAND_NUMBERS)
    
    @staticmethod
    def GetCommandNames():
        return(POD_Basics.__COMMAND_NAMES)

    @staticmethod
    def GetCommandDescriptions():
        return(POD_Basics.__COMMAND_DESCRIPTIONS)

    @staticmethod
    def ChecksumInt(byteArr):
        # sum together all bytes in byteArr
        sum = 0
        for b in byteArr : 
            sum = sum + b
        # invert and get last byte 
        checksum  = ~sum & 0xFF
        # return the checksum 
        return(checksum)

    @staticmethod
    def ChecksumBytes(byteArr):
        # calculate checksum 
        checksum = POD_Basics.ChecksumInt(byteArr)
        # get hex string
        cs_str = hex(checksum)
        length = len(cs_str)
        # get last two characters and make uppercase
        b0_char = cs_str[length-2].upper()
        b1_char = cs_str[length-1].upper()
        # get ascii code for characters
        b0_ascii = ord(b0_char)
        b1_ascii = ord(b1_char)
        # get bytes from ascii 
        b = bytes([b0_ascii,b1_ascii])
        # return checksum converted to bytes
        return(b)

    @staticmethod
    def PODpacket_standard() : 
        pass


    @staticmethod
    def PODpacket_payload(payload) :   
        pass 

    # ====== DUNDER METHODS ======

    def __init__(self, port, baudrate=9600, allowBinaryPackets=False) : 
        # initialize serial port 
        super().__init__(port, baudrate=baudrate)
        # flag if binary packets are allowed 
        self.__allowBinaryPackets = allowBinaryPackets
