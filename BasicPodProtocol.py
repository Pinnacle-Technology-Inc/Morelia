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
    def STX():
        # return STX character used to indicate start of a packet 
        return(bytes.fromhex('02'))

    @staticmethod
    def ETX():
        # return ETX character used to indicate end of a packet 
        return(bytes.fromhex('03'))

    @staticmethod
    def ValueToBytes(value, numBytes) : 
        # convert number into a hex string and remove the '0x' prefix
        num_hexStr = hex(value).replace('0x','')

        # split into list to access each digit, and make each hex character digit uppercase 
        num_hexStr_list = [x.upper() for x in num_hexStr]
        
        # convert each digit to an ascii code
        asciilist = []
        for character in num_hexStr_list: 
            # convert character to its ascii code and append to list  
            asciilist.append(ord(character))

        # get bytes for the ascii number 
        blist = []
        for ascii in asciilist :
            # convert ascii code to bytes and add to list 
            blist.append(bytes([ascii]))
        
        # if the number of bytes is smaller that requested, add zeros to beginning of the bytes to get desired size
        if (len(blist) < numBytes): 
            # ascii code for zero
            zero = bytes([ord('0')])
            # create list of zeros with size (NumberOfBytesWanted - LengthOfCurrentBytes))
            pre = [zero] * (numBytes - len(blist))
            # concatenate zeros list to remaining bytes
            post = pre + blist
        # if the number of bytes is greater that requested, keep the lowest bytes, remove the overflow 
        elif (len(blist) > numBytes) : 
            # get minimum index of bytes to keep
            min = len(blist) - numBytes
            # get indeces from min to end of list 
            post = blist[min:]
        # if the number of bytes is equal to that requested, keep the all the bytes, change nothing
        else : 
            post = blist

        # initialize message to first byte in 'post'
        msg = post[0]
        for i in range(numBytes-1) : 
            # concatenate next byte to end of the message 
            msg = msg + post[i+1]

        # return a byte message of a desired size 
        return(msg)


    @staticmethod
    def Checksum(bytesIn):
        # sum together all bytes in byteArr
        sum = 0
        for b in bytesIn : 
            sum = sum + b
        # invert and get last byte 
        cs  = ~sum & 0xFF
        # convert int into bytes 
        cs_bytes = POD_Basics.ValueToBytes(cs, 2)
        # return checksum bytes
        return(cs_bytes)


    @staticmethod
    def PODpacket_standard(commandNumber) : 
        # prepare components of packet
        stx = POD_Basics.STX()                          # STX indicating start of packet (1 byte)
        cmd = POD_Basics.ValueToBytes(commandNumber, 4) # command number (4 bytes)
        csm = POD_Basics.Checksum(cmd)                  # checksum (2 bytes)
        etx = POD_Basics.ETX()                          # ETX indicating end of packet (1 byte)
        # concatenate packet components
        packet = stx + cmd + csm + etx                  # pod packet (8 bytes)
        # return complete bytes packet
        return(packet)


    @staticmethod
    def PODpacket_payload(commandNumber, payload) :   
        # prepare components of packet
        stx = POD_Basics.STX()                          # STX indicating start of packet (1 byte)
        cmd = POD_Basics.ValueToBytes(commandNumber, 4) # command number (4 bytes)
        csm = POD_Basics.Checksum(cmd)                  # checksum (2 bytes)
        etx = POD_Basics.ETX()                          # ETX indicating end of packet (1 byte)
        # concatenate packet components with payload
        packet = stx + cmd + payload + csm + etx
        # return complete bytes packet
        return(packet) 


    # ====== DUNDER METHODS ======

    def __init__(self, port, baudrate=9600, allowBinaryPackets=False) : 
        # initialize serial port 
        super().__init__(port, baudrate=baudrate)
        # flag if binary packets are allowed 
        self.__allowBinaryPackets = allowBinaryPackets


    # ====== PUBLIC METHODS ======

    def Set_AllowBinaryPackets(self, flag) : 
        # set the class instance's flag to allow binary packets to 'flag' parameter
        self.__allowBinaryPackets = flag

    def Get_AllowBinaryPackets(self) : 
        return(self.__allowBinaryPackets)