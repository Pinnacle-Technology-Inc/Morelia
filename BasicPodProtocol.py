from Serial_InOut import COM_io

class POD_Basics(COM_io) : 

    # ====== GLOBAL VARIABLES ======

    __standard_commandNumbers  = [0,1,2,3,4,5,7,8,9,10,12]
    __payload_commandNumbers   = [6] #,11] # 11 is binary... figure this one out later
    __payload_argumentBytes    = [2] #,??]

    # ====== STATIC METHODS ======

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

    # ------ GETTERS ------

    def GetStandardCommandNumbers(self):
        return(self.__standard_commandNumbers)
    
    def GetPayloadCommandNumbers(self):
        return(self.__payload_commandNumbers)
    
    def GetPayloadArgumentBytes(self):
        self.__payload_argumentBytes

    # ------ SETTERS ------

    def SetStandardCommands(self, cmdList) : 
            self.__standard_commandNumbers = cmdList

    def SetPayloadCommands(self, cmdList, argList) : 
            self.__payload_commandNumbers = cmdList
            self.__payload_argumentBytes = argList

    # ------ POD FUNCTIONS ------

    def WriteStandardPacket(self, commandNumber) : 
        # throw exception if command number is invalid 
        if(commandNumber not in self.__standard_commandNumbers) : 
            raise Exception('Invalid POD command.')
        # build packet
        packet = POD_Basics.PODpacket_standard(commandNumber)
        # write packet to serial port 
        self.Write(packet)

    def ReadPodPacket(self) : 
        # read from serial port until ETX
        packet = self.ReadUntil(POD_Basics.ETX())
        # return packet 
        return(packet)