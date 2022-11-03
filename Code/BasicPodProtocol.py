from Serial_InOut import COM_io

class POD_Basics(COM_io) : 

    # ====== GLOBAL VARIABLES ======

    # index keys for __commands dict values 
    __NAME      = 0
    __ARGUMENTS = 1
    __RETURNS   = 2

    __commands = {
        # key(command number) : value([command name, number of argument ascii bytes, number of return bytes]) 
        0   : [ 'ACK',                  0,      0       ],
        1   : [ 'NACK',                 0,      0       ],
        2   : [ 'PING',                 0,      0       ],
        3   : [ 'RESET',                0,      0       ],
        4   : [ 'ERROR',                0,      2       ],
        5   : [ 'STATUS',               0,      0       ],
        6   : [ 'STREAM',               2,      2       ], 
        7   : [ 'BOOT',                 0,      0       ],
        8   : [ 'TYPE',                 0,      2       ],
        9   : [ 'ID',                   0,      0       ],
        10  : [ 'SAMPLE RATE',          0,      0       ],
        11  : [ 'BINARY',               0,      None    ],  # No return bytes because the length depends on the message
        12  : [ 'FIRMWARE VERSION',     0,      6       ]
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
    def AsciiBytesToInt(msg_b):
        # convert bytes to str and remove byte wrap (b'XXXX' --> XXXX)
        msg_str = str(msg_b) [2 : len(str(msg_b))-1]
        # convert string into base 16 int (reads string as hex number, returns decimal int)
        msg_int = int(msg_str,16)
        # return int
        return(msg_int)


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
    def PODpacket_Standard(commandNumber) : 
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
    def PODpacket_StandardWithPayload(commandNumber, payload) :   
        # prepare components of packet
        stx = POD_Basics.STX()                          # STX indicating start of packet (1 byte)
        cmd = POD_Basics.ValueToBytes(commandNumber, 4) # command number (4 bytes)
        csm = POD_Basics.Checksum(cmd+payload)          # checksum (2 bytes)
        etx = POD_Basics.ETX()                          # ETX indicating end of packet (1 byte)
        # concatenate packet components with payload
        packet = stx + cmd + payload + csm + etx
        # return complete bytes packet
        return(packet) 

    @staticmethod
    def UnpackPodCommand_Standard(msg) : 
        # standard POD packet with optional payload = 
        #   STX (1 byte) + command number (4 bytes) + optional packet (? bytes) + checksum (2 bytes) + ETX (1 bytes)
        MINBYTES=8

        # get number of bytes in message
        packetBytes = len(msg)

        # message must have enough bytes, start with STX, or end with ETX
        if(    (packetBytes < MINBYTES)
            or (msg[0].to_bytes(1,'big') != POD_Basics.STX()) 
            or (msg[packetBytes-1].to_bytes(1,'big') != POD_Basics.ETX())
        ) : 
            raise Exception('Cannot unpack POD command.')

        # create dict and add command number, payload, and checksum
        msg_unpacked = {}
        msg_unpacked['Command Number']  = msg[1:5]                                  # 4 bytes after STX
        if( (packetBytes - MINBYTES) > 0) : # add packet to dict, if available 
            msg_unpacked['Payload']     = msg[5:(packetBytes-3)]                    # remaining bytes between command number and checksum 
        msg_unpacked['Checksum']        = msg[(packetBytes-3):(packetBytes-1)]      # 2 bytes before ETX

        # return unpacked POD command
        return(msg_unpacked)
        

    @staticmethod
    def UnpackPodCommand_VariableBinary(msg) : 
        # variable binary POD packet = 
        #   STX (1 byte) + command number (4 bytes) + length of binary (4 bytes) + checksum (2 bytes) + ETX (1 bytes)    <-- STANDARD POD COMMAND
        #   + binary (LENGTH bytes) + checksum (2 bytes) + ETX (1 bytes)                                                 <-- BINARY DATA
        MINBYTES = 15

        # get number of bytes in message
        packetBytes = len(msg)

        # message must have enough bytes, start with STX, have ETX after POD command, or end with ETX
        if(    (packetBytes < MINBYTES)                        
            or (msg[0].to_bytes(1,'big') != POD_Basics.STX()) 
            or (msg[11].to_bytes(1,'big') != POD_Basics.ETX())
            or (msg[packetBytes-1].to_bytes(1,'big') != POD_Basics.ETX())
        ) : 
            raise Exception('Cannot unpack POD command.')

        # create dict and add command number and checksum
        msg_unpacked = {
            'Command Number'        : msg[1:5],                                 # 4 bytes after STX
            'Binary Packet Length'  : msg[5:9],                                 # 4 bytes after command number 
            'Checksum'              : msg[9:11],                                # 2 bytes before ETX
            'Binary Data'           : msg[12:(packetBytes-3)],                  # ? bytes after ETX
            'Binary Checksum'       : msg[(packetBytes-3) : (packetBytes-1)]    # 2 bytes before binary ETX
        }

        # return unpacked POD command with variable length binary packet 
        return(msg_unpacked)

    # ====== DUNDER METHODS ======

    def __init__(self, port, baudrate=9600) : 
        # initialize serial port 
        super().__init__(port, baudrate=baudrate)
        # want to initialize anything else? do that here :)


    # ====== PUBLIC METHODS ======

    # ------ COMMAND DICT ACCESS ------
        
    def GetCommands(self):
        return(self.__commands)

    def AddCommand(num,name,arg,ret):
        # TODO
        pass

    def RemoveCommand(cmd) :
        # TODO
        pass

    def CommandNumber(self, name) : 
        # search through dict to find key 
        for key,val in self.__commands.items() :
            if(name == val[self.__NAME]) : 
                return(key)
        # no match
        return(None)

    def ArgumentBytes(self, cmd) : 
        # search through dict to find matching entry  
        for key,val in self.__commands.items() :
            if(cmd == key or cmd == val[self.__NAME]) : 
                # return the number of bytes in the command return 
                return(val[self.__ARGUMENTS])
        # no match
        return(None) 

    def ReturnBytes(self,cmd) : 
        # search through dict to find matching entry  
        for key,val in self.__commands.items() :
            if(cmd == key or cmd == val[self.__NAME]) : 
                # return the number of bytes in the command return 
                return(val[self.__RETURNS])
        # no match
        return(None) 

    def DoesCommandExist(self, cmd) : 
        # initialize to false
        isValidCmd = False
        # check each command number and name to try to find match 
        for key,val in self.__commands.items() : 
            if(cmd==key or cmd==val[self.__NAME]):
                # set to true if match found 
                isValidCmd = True
        # return true if the command is in the command dict, false otherwise
        return(isValidCmd)

    # ------ POD COMMUNICATION ------

    def WritePacket(self, cmd, payload=None) : 
        # return False if command is not valid
        if(not self.DoesCommandExist(cmd)) : 
            return(False)

        # get command number 
        if(isinstance(cmd,str)):
            cmdNum = self.CommandNumber(cmd)
        else: 
            cmdNum = cmd

        # build payload packet if a packet is given 
        if(payload):
            # return False if payload is not the correct size
            if( len(payload) != self.ArgumentBytes(cmdNum)):
                return(False)
            # build packet with paylaod 
            packet = POD_Basics.PODpacket_StandardWithPayload(cmdNum, payload)
        # otherwise, build standard packet 
        else : 
            # write standard packet to serial port 
            packet = POD_Basics.PODpacket_Standard(cmdNum)

        # write packet to serial port 
        self.Write(packet)
        # return true to mark successful write :)
        return(True)

    def ReadPODpacket_Standard(self) : # assume non-binary 
        # initialize 
        time    = 0
        TIMEOUT = 1000   
        b       = None 

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
            raise Exception('Timeout when reading from POD device.')

        # return packet containing STX+message+ETX
        return(packet)

    def ReadPODpacket_VariableBinary(self) :
        # Variable binary packet: contain a normal POD packet with the binary command, 
        # and the payload is the length of the binary portion. 
        # The binary portion also includes an ASCII checksum and ETX.
        #  BYTES    : POSITION                        : CONTENTS          -- TIPS
        # ------------------------------------------------------------------------------------
        #  1        : 0                               : STX               -- BEGIN STANDARD POD PACKET 
        #  4        : 1-4                             : COMMAND
        #  4        : 5-8                             : LENGTH
        #  2        : 9-10                            : CHECKSUM
        #  1        : 11                              : ETX               -- END STANDARD POD PACKET
        #  LENGTH   : 12-(12+LENGTH)                  : BINARY DATA       -- BEGIN BINARY PACKET
        #  2        : (12+LENGTH+1) - (12+LENGTH+3)   : BINARY CHECKSUM
        #  1        : (12+LENGTH+4)                   : ETX               -- END BINARY PACKET
        
        # read standard POD packet
        start = self.ReadPODpacket_Standard()
        startDict = self.UnpackPodCommand_Standard(start)

        # check if command number is valid, return if not
        cmd = self.AsciiBytesToInt(startDict['Command Number'])
        if(not self.DoesCommandExist(cmd)) : 
            raise Exception('Invalid binary POD command.')

        # read binary packet length
        numOfbinaryBytes = self.AsciiBytesToInt(startDict['Payload'])
    
        # continue reading  packet
        binaryMsg  = self.Read(numOfbinaryBytes)
        binaryCsm  = self.Read(2)
        binaryLast = self.Read(1)

        # verify that Last is ETX
        if(binaryLast != self.ETX()) : 
            raise Exception('Bad binary read.')

        # build complete message
        packet = start + binaryMsg + binaryCsm + binaryLast

        # return complete variable length binary packet
        return(packet)