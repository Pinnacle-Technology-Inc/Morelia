from SerialCommunication import COM_io
from PodCommands import POD_Commands

class POD_Basics : 

    # ============ GLOBAL CONSTANTS ============    ========================================================================================================================


    # number of active POD devices, maintained by __init__ and __del__ 
    __NUMPOD = 0


    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self, port, baudrate=9600) : 
        # initialize serial port 
        self._port = COM_io(port, baudrate)
        # create object to handle commands 
        self._commands = POD_Commands()
        # increment number of POD device counter
        POD_Basics.__NUMPOD += 1


    def __del__(self):
        # decrement number of POD device counter
        POD_Basics.__NUMPOD -= 1


    # ============ STATIC METHODS ============      ========================================================================================================================
    

    # ------------ CLASS GETTERS ------------   ------------------------------------------------------------------------------------------------------------------------


    @staticmethod
    def GetNumberOfPODDevices() :
        # returns the counter tracking the number of active pod devices
        return(POD_Basics.__NUMPOD)


    # ------------ USEFUL VALUES ------------   ------------------------------------------------------------------------------------------------------------------------


    @staticmethod
    def STX():
        # return STX character used to indicate start of a packet 
        return(bytes.fromhex('02'))


    @staticmethod
    def ETX():
        # return ETX character used to indicate end of a packet 
        return(bytes.fromhex('03'))


    # ------------ CONVERSIONS ------------     ------------------------------------------------------------------------------------------------------------------------


    @staticmethod
    def IntToAsciiBytes(value, numBytes) : 
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
    def BinaryBytesToInt(msg, byteorder='big', signed=False) :
        # convert a binary message represented by bytes into an integer
        return(int.from_bytes(msg,byteorder=byteorder,signed=signed))


    # ------------ POD PACKETS ------------         ------------------------------------------------------------------------------------------------------------------------


    @staticmethod
    def Checksum(bytesIn):
        # sum together all bytes in byteArr
        sum = 0
        for b in bytesIn : 
            sum = sum + b
        # invert and get last byte 
        cs  = ~sum & 0xFF
        # convert int into bytes 
        cs_bytes = POD_Basics.IntToAsciiBytes(cs, 2)
        # return checksum bytes
        return(cs_bytes)


    @staticmethod
    def ValidateChecksum_Standard(msg):
        # assume that msg contains STX + packet + csm + ETX. 
        # This assumption is good for more all pod packets (except variable length binary packet)
        packetBytes = len(msg)
        # get message contents excluding STX/ETX
        msgPacket = msg[1:packetBytes-3]
        msgCsm = msg[packetBytes-3:packetBytes-1]
        # calculate checksum from content packet  
        csmValid = POD_Basics.Checksum(msgPacket)
        # return True if checksums match 
        if(msgCsm == csmValid) :
            return(True)
        else:
            return(False)


    @staticmethod
    def ValidateChecksum_Binary(msg) :
        # unpack standard POD packet 
        msgDict = POD_Basics.UnpackPODpacket_Standard(msg) 

        # recreate POD packets 
        packetPre = msgDict['Command Number'] + msgDict['Command Number'] + msgDict['Binary Packet Length']
        packetBin = msgDict['Binary Data']

        # get checksums 
        csmPreValid = POD_Basics.Checksum(packetPre)
        csmBinValid = POD_Basics.Checksum(packetBin)
        csmPre = msgDict['Checksum']
        csmBin = msgDict['Binary Checksum']

        # return True if both checksums are valid  
        if(csmPre==csmPreValid and csmBin==csmBinValid) :
            return(True)
        else :
            return(False)


    @staticmethod
    def PODpacket_Standard(commandNumber, payload=None) : 
        # prepare components of packet
        stx = POD_Basics.STX()                              # STX indicating start of packet (1 byte)
        cmd = POD_Basics.IntToAsciiBytes(commandNumber, 4)  # command number (4 bytes)
        etx = POD_Basics.ETX()                              # ETX indicating end of packet (1 byte)
        # build packet with payload 
        if(payload) :
            csm = POD_Basics.Checksum(cmd+payload)          # checksum (2 bytes)
            packet = stx + cmd + payload + csm + etx        # pod packet with payload (8 + payload bytes)
        # build packet with NO payload 
        else :
            csm = POD_Basics.Checksum(cmd)                  # checksum (2 bytes)
            packet = stx + cmd + csm + etx                  # pod packet (8 bytes)
        # return complete bytes packet
        return(packet)


    @staticmethod
    def UnpackPODpacket_Standard(msg) : 
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
            raise Exception('Cannot unpack an invalid POD packet.')

        # create dict and add command number, payload, and checksum
        msg_unpacked = {}
        msg_unpacked['Command Number']  = msg[1:5]                                  # 4 bytes after STX
        if( (packetBytes - MINBYTES) > 0) : # add packet to dict, if available 
            msg_unpacked['Payload']     = msg[5:(packetBytes-3)]                    # remaining bytes between command number and checksum 
        # msg_unpacked['Checksum']        = msg[(packetBytes-3):(packetBytes-1)]      # 2 bytes before ETX

        # return unpacked POD command
        return(msg_unpacked)


    @staticmethod
    def UnpackPODpacket_VariableBinary(msg) : 
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
            raise Exception('Cannot unpack an invalid POD packet.')

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

    
    @staticmethod
    def TranslatePODpacket_Standard(msg) : 
        # unpack parts of POD packet into dict
        msgDict = POD_Basics.UnpackPODpacket_Standard(msg)
        # initialize dictionary for translated values 
        msgDictTrans = {}
        # translate the binary ascii encoding into a readable integer
        msgDictTrans['Command Number']  = POD_Basics.AsciiBytesToInt(msgDict['Command Number'])
        if( 'Payload' in msgDict) :
            msgDictTrans['Payload']     = POD_Basics.AsciiBytesToInt(msgDict['Payload'])
        # msgDictTrans['Checksum']        = POD_Basics.AsciiBytesToInt(msgDict['Command Number'])
        # return translated unpacked POD packet 
        return(msgDictTrans)

   
    @staticmethod
    def TranslatePODpacket_Binary(msg) : 
        pass
    

    # ============ PUBLIC METHODS ============      ========================================================================================================================


    # ------------ COMMAND DICT ACCESS ------------ ------------------------------------------------------------------------------------------------------------------------
        

    def GetDeviceCommands(self):
        # Get commands from this instance's command dict object 
        return(self._commands.GetCommands())


    # ------------ POD COMMUNICATION ------------   ------------------------------------------------------------------------------------------------------------------------


    def WritePacket(self, cmd, payload=None) : 
        # return False if command is not valid
        if(not self._commands.DoesCommandExist(cmd)) : 
            return(False)

        # get command number 
        if(isinstance(cmd,str)):
            cmdNum = self._commands.CommandNumberFromName(cmd)
        else: 
            cmdNum = cmd

        # check if the command requires a payload
        argSize = self._commands.ArgumentBytes(cmdNum)
        if(argSize > 0) : 
            # check to see if a payload was given 
            if(not payload):
                raise Exception('POD command requires a payload.')
            # then check that payload is of correct type
            elif(not isinstance(payload, bytes)) :
                raise Exception('Payload must be of type(bytes).')
            # then check that payload is of correct size
            elif(len(payload) != argSize):
                raise Exception('Payload is the wrong size.')
            # else : everything is good! continue 

        # build POD packet 
        packet = self.PODpacket_Standard(cmdNum, payload=payload)

        # write packet to serial port 
        self._port.Write(packet)

        # returns packet that was written
        return(packet)


    def ReadPODpacket(self, validateChecksum=True):
        # read until STX is found
        b = None
        while(b != self.STX()) :
            b = self._port.Read(1)     # read next byte  
        # continue reading packet  
        packet = self.__ReadPODpacket_Recursive(validateChecksum=validateChecksum)
        # return final packet
        return(packet)


    # ============ PRIVATE METHODS ============      ========================================================================================================================

    def __ReadPODpacket_Recursive(self, validateChecksum=True) : 
        # start packet with STX
        packet = self.STX()

        # read next 4 bytes of the command number 
        cmd = self.__Read_GetCommand(validateChecksum=validateChecksum)
        packet += cmd 

        # return packet if cmd ends in ETX
        if(cmd[len(cmd)-1].to_bytes(1,'big') == self.ETX()) : 
            return(packet)

        # determine the command number
        cmdNum = self.AsciiBytesToInt(cmd)

        # check if command number is valid
        if( not self._commands.DoesCommandExist(cmdNum) ) :
            raise Exception('Cannot read an invalid command: ', cmdNum)
        

        # then check if it is standard or binary
        if( self._commands.IsCommandBinary(cmdNum) ) : 
            # binary read
            packet = self.__Read_Binary(prePacket=packet, validateChecksum=validateChecksum)
        else : 
            # standard read 
            packet = self.__Read_Standard(prePacket=packet, validateChecksum=validateChecksum)

        # return packet
        return(packet)


    def __Read_GetCommand(self, validateChecksum=True) : 
        # initialize 
        cmd = None
        cmdCounter = 0

        # read next 4 bytes to get command number
        while(cmdCounter < 4) : 
            # read next byte 
            b = self._port.Read(1)
            cmdCounter += 1
            # build command packet 
            if(cmd == None) : 
                cmd = b
            else : 
                cmd += b
            # start over if STX is found 
            if(b == self.STX() ) : 
                self.__ReadPODpacket_Recursive(validateChecksu=validateChecksum)
            # return if ETX is found
            if(b == self.ETX() ) : 
                return(cmd)

        # return complete 4 byte long command packet
        return(cmd)

    def __Read_Standard(self, prePacket, validateChecksum=True):
        # read until ETX 
        packet = prePacket + self.__Read_ReadToETX(validateChecksum=validateChecksum)

        # check for valid  
        if(validateChecksum) :
            if( not self.ValidateChecksum_Standard(packet) ) :
                raise Exception('Bad checksum for standard POD packet read.')

        # return packet
        return(packet)

    def __Read_ReadToETX(self, validateChecksum=True) : 
        # initialize 
        packet = None
        b = None
        # stop reading after finding ETX
        while(b != self.ETX()) : 
            # read next byte
            b = self._port.Read(1)
            # build packet 
            if(packet == None) : 
                packet = b
            else : 
                packet += b
            # start over if STX
            if(b == self.STX()) : 
                self.__ReadPODpacket_Recursive(validateChecksum=validateChecksum)
        # return packet
        return(packet)

    def __Read_Binary(self, prePacket, validateChecksum=True):
        # Variable binary packet: contain a normal POD packet with the binary command, 
        #   and the payload is the length of the binary portion. The binary portion also 
        #   includes an ASCII checksum and ETX.        
         
        # read standard POD packet 
        startPacket = prePacket + self.__Read_ReadToETX(validateChecksum=validateChecksum)
        startDict = self.UnpackPODpacket_Standard(startPacket)

        # get length of binary packet 
        numOfbinaryBytes = self.AsciiBytesToInt(startDict['Payload'])

        # read binary packet
        binaryMsg = self._port.Read(numOfbinaryBytes) # read binary packet

        # read csm and etx
        binaryEnd = self.__Read_ReadToETX(validateChecksum=validateChecksum)

        # build complete message
        packet = startPacket + binaryMsg + binaryEnd

        # check if checksum is correct 
        if(validateChecksum):
            if(not self.ValidateChecksum_Binary(packet) ) :
                raise Exception('Bad checksum for binary POD packet read.')

        # return complete variable length binary packet
        return(packet)




    # def __ReadPODpacket_Standard(self, validateChecksum=True) :
    #     # initialize 
    #     time    = 0
    #     TIMEOUT = 1000   
    #     b       = None 

    #     # read until STX found
    #     while(b != self.STX() and time<TIMEOUT) :
    #         time += 1                   # increment counter
    #         b = self._port.Read(1)     # read next byte  

    #     # set first byte of packet to STX
    #     packet = b

    #     # get bytes until ETX, or start over at next STX
    #     while(b != self.ETX() and time<TIMEOUT) : 
    #         time += 1                   # increment counter
    #         b = self._port.Read(1)     # read next byte
    #         # check if STX
    #         if(b == self.STX()):
    #             # forget previous packet and start with STX 
    #             packet =  b
    #         else : 
    #             # append byte to end message
    #             packet = packet + b

    #     # raise exception if timeout occurs
    #     if(time==TIMEOUT) : 
    #         raise Exception('Timeout when reading from POD device.')

    #     if(validateChecksum) :
    #         # raise exception if chacksum is invalid
    #         if(POD_Basics.ValidateChecksum(packet) == False ):
    #             raise Exception('Bit error in recieved POD message.')

    #     # return packet containing STX+message+ETX
    #     return(packet)



# =====================================================================================================================================================
# HANDLE THESE FUNCTIONS ELSEWHERE
# =====================================================================================================================================================
""""

    @staticmethod
    def IsPodPacketValid_VariableBinary(msg) :
        # unpack standard POD packet 
        msgDict = POD_Basics.UnpackPODpacket_Standard(msg) 

        # recreate POD packets 
        packetPre = msgDict['Command Number'] + msgDict['Command Number'] + msgDict['Binary Packet Length']
        packetBin = msgDict['Binary Data']

        # get checksums 
        csmPreValid = POD_Basics.Checksum(packetPre)
        csmBinValid = POD_Basics.Checksum(packetBin)
        csmPre = msgDict['Checksum']
        csmBin = msgDict['Binary Checksum']

        # return True if both checksums are valid  
        if(csmPre==csmPreValid and csmBin==csmBinValid) :
            return(True)
        else :
            return(False)


    @staticmethod
    def UnpackPODpacket_VariableBinary(msg) : 
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
            raise Exception('Cannot unpack an invalid POD packet.')

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

    def ReadPODpacket_VariableBinary(self) :
        # Variable binary packet: contain a normal POD packet with the binary command, 
        #   and the payload is the length of the binary portion. The binary portion also 
        #   includes an ASCII checksum and ETX.
        
        # read standard POD packet
        start = self.ReadPODpacket_Standard()
        startDict = self.UnpackPODpacket_Standard(start)

        # check if command number is valid, return if not
        cmd = self.AsciiBytesToInt(startDict['Command Number'])
        if(not self._commands.DoesCommandExist(cmd)) : 
            raise Exception('Invalid binary POD command.')

        # read binary packet length
        numOfbinaryBytes = self.AsciiBytesToInt(startDict['Payload'])
    
        # continue reading packet
        binaryMsg  = self._port.Read(numOfbinaryBytes) # read binary packet
        binaryCsm  = self._port.Read(2)                # read checksum
        binaryLast = self._port.Read(1)                # read ETX

        # verify that Last is ETX
        if(binaryLast != self.ETX()) : 
            raise Exception('Bad binary read.')

        # build complete message
        packet = start + binaryMsg + binaryCsm + binaryLast

        # return complete variable length binary packet
        return(packet)

"""