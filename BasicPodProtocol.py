from Serial_InOut import COM_io

class POD_Basics(COM_io) : 

    # ====== GLOBAL VARIABLES ======

    # index keys for dict values 
    __NAME = 0
    __RETURNS = 1
    __ARGUMRNTS = 2

    __standard_commands = {
        # key(command number) : value([command name, return bytes]) 
        0   : [ 'ACK',                  0       ],
        1   : [ 'NACK',                 0       ],
        2   : [ 'PING',                 0       ],
        3   : [ 'RESET',                0       ],
        4   : [ 'ERROR',                1       ],
        5   : [ 'STATUS',               None    ],  # NONE is placeholder, I dont know this now
        7   : [ 'BOOT',                 None    ],
        8   : [ 'TYPE',                 1       ],
        9   : [ 'ID',                   None    ],
        10  : [ 'SAMPLE RATE',          None    ],
        12  : [ 'FIRMWARE VERSION',     3       ]
    }

    __payload_commands = {
        # key(command number) : value([command name, number of argument bytes, number of return bytes]) 
        6   : [ 'STREAM',               1,      1   ] 
    }

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
        csm = POD_Basics.Checksum(cmd+payload)          # checksum (2 bytes)
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
        return(self.__standard_commands)
    
    def GetPayloadCommandNumbers(self):
        return(self.__payload_commands)

    # ------ SETTERS ------

    def SetStandardCommands(self, cmdDict) : 
            self.__standard_commands = cmdDict

    def SetPayloadCommands(self, cmdDict) : 
            self.__payload_commands = cmdDict

    # ------ POD FUNCTIONS ------

    def GetCommandNumber_Standard(self, name) : 
        # search through dict to find key 
        for key,val in self.__standard_commands.items() :
            if(name == val) : 
                return(key)
        # no match
        return(None)

    def GetCommandNumber_Payload(self, name) : 
        # search through dict to find key 
        for key,val in self.__payload_commands.items() :
            if(name == val[self.NAME]) : 
                # return the command number 
                return(key)
        # no match
        return(None) 

    def GetArgumentBytes_Payload(self, cmd) :
        # search through dict to find matching entry  
        for key,val in self.__payload_commands.items() :
            if(cmd == key or cmd == val[self.NAME]) : 
                # return the number of bytes in the command return 
                return(val[self.ARGUMRNTS])
        # no match
        return(None) 

    def WriteStandardPacket(self, cmd) : 
        # throw exception if command number is invalid 
        if(cmd not in self.__standard_commands) : 
            raise Exception('Invalid POD command.')

        # get command number 
        if(isinstance(cmd,str)):
            cmdNum = self.GetCommandNumber_Standard(cmd)
        else: 
            cmdNum = cmd

        # build packet
        packet = POD_Basics.PODpacket_standard(cmdNum)

        # write packet to serial port 
        self.Write(packet)

    def WritePayloadPacket(self, cmd, payload) : 
        # throw exception if command number is invalid 
        isValidCmd = False
        for key,val in self.__payload_commandNumbers.items() : 
            if(cmd==key or cmd==val[self.NAME]):
                isValidCmd = True
        if(not isValidCmd) :
            raise Exception('Invalid POD command number.')

        # throw exception if payload is wrong size 
        payloadSize = self.GetArgumentBytes_Payload(cmd)
        if(len(payload) != payloadSize):
            raise Exception('POD packet payload is invalid.')

        # get command number 
        if(isinstance(cmd,str)):
            cmdNum = self.GetCommandNumber_Payload(cmd)
        else: 
            cmdNum = cmd

        # build packet
        packet = POD_Basics.PODpacket_payload(cmdNum, payload)

        # write packet to serial port 
        self.Write(packet)


    def ReadPodPacket(self) :      
        # init
        time = 0
        TIMEOUT = 100   
        b = None 

        # read until STX found
        while(b != self.STX() and time<TIMEOUT) :
            time += 1           # increment counter
            b = self.Read(1)    # read next byte  

        # set first byte of packet to STX
        packet = b

        # get bytes until ETX, or start over at next STX
        while(b != self.ETX() and time<TIMEOUT) : 
            time += 1           # increment counter
            b = self.Read(1)    # read next byte
            # check if STX
            if(b == self.STX()):
                # forget previous packet and start with STX 
                packet =  b
            else : 
                # append byte to end message
                packet = packet + b

        # raise exception if timeout occurs
        if(time==TIMEOUT) : 
            raise Exception('Timout when reading from POD device.')

        # return packet containing STX+message+ETX
        return(packet)


# TODO 
# 1. change how to handle command numbers and stuff. Instead of a list, use a tuple/dict. Store the command number, name, and argument (if applicable)
