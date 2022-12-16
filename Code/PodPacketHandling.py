
class POD_Packets() : 

    # ============ STATIC METHODS ============      ========================================================================================================================


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


    # ------------ BUILD PACKET ------------             ------------------------------------------------------------------------------------------------------------------------
 

    @staticmethod
    def Checksum(bytesIn):
        # sum together all bytes in byteArr
        sum = 0
        for b in bytesIn : 
            sum = sum + b
        # invert and get last byte 
        cs  = ~sum & 0xFF
        # convert int into bytes 
        cs_bytes = POD_Packets.IntToAsciiBytes(cs, 2)
        # return checksum bytes
        return(cs_bytes)


    @staticmethod
    def BuildPODpacket_Standard(commandNumber, payload=None) : 
        # prepare components of packet
        stx = POD_Packets.STX()                              # STX indicating start of packet (1 byte)
        cmd = POD_Packets.IntToAsciiBytes(commandNumber, 4)  # command number (4 bytes)
        etx = POD_Packets.ETX()                              # ETX indicating end of packet (1 byte)
        # build packet with payload 
        if(payload) :
            csm = POD_Packets.Checksum(cmd+payload)         # checksum (2 bytes)
            packet = stx + cmd + payload + csm + etx        # pod packet with payload (8 + payload bytes)
        # build packet with NO payload 
        else :
            csm = POD_Packets.Checksum(cmd)                 # checksum (2 bytes)
            packet = stx + cmd + csm + etx                  # pod packet (8 bytes)
        # return complete bytes packet
        return(packet)