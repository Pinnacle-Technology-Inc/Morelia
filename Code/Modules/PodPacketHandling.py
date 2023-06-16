

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class POD_Packets() : 
    """
    POD_Packets is a collection of methods for creating and interpreting POD packets. 
    """

    # ============ STATIC METHODS ============      ========================================================================================================================


    # ------------ USEFUL VALUES ------------   ------------------------------------------------------------------------------------------------------------------------


    @staticmethod
    def STX() -> bytes :
        """Get start-of-transmission (STX) character in bytes. STX marks the starting byte of a POD Packet.

        Returns:
            bytes: Bytes for STX (0x02).
        """
        # return STX character used to indicate start of a packet 
        return(bytes.fromhex('02'))


    @staticmethod
    def ETX() -> bytes :
        """Get end-of-transmission (ETX) character in bytes. ETX marks the end byte of a POD Packet.

        Returns:
            bytes: Bytes for ETX(0x03).
        """
        # return ETX character used to indicate end of a packet 
        return(bytes.fromhex('03'))


    # ------------ CONVERSIONS ------------     ------------------------------------------------------------------------------------------------------------------------


    @staticmethod
    def TwosComplement(val: int, nbits: int) -> int :
        """Gets the 2's complement of the argument value.

        Args:
            val (int): Value to be complemented.
            nbits (int): Number of bits in the value.

        Returns:
            int: Integer of the 2's complement for the val.
        """
        # value is negative 
        if (val < 0) :
            val = (1 << nbits) + val
        # value is positive 
        else:
            # If sign bit is set.  compute negative value.
            if ( (val & (1 << (nbits - 1))) != 0 ):
                val = val - (1 << nbits)
        return val


    @staticmethod
    def IntToAsciiBytes(value: int, numChars: int) -> bytes : 
        """Converts an integer value into ASCII-encoded bytes. 
        
        First, it converts the integer value into a usable uppercase hexadecimal string. Then it converts the 
        ASCII code for each character into bytes. Lastly, it ensures that the final message is the desired length.  

        Example: if value=2 and numBytes=4, the returned ASCII will show b'0002', which is '0x30 0x30 0x30 0x32' 
        in bytes. Uses the 2's complement if the val is negative. 

        Args:
            value (int): Integer value to be converted into ASCII-encoded bytes.
            numChars (int): Number characters to be the length of the ASCII-encoded message.

        Returns:
            bytes: Bytes that are ASCII-encoded conversions of the value parameter.
        """
        # get 2C if signed 
        if(value < 0) : 
            val = POD_Packets.TwosComplement(value, numChars*4)
        else : 
            val = value

        # convert number into a hex string and remove the '0x' prefix
        num_hexStr = hex(val).replace('0x','')

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
        if (len(blist) < numChars): 
            # ascii code for zero
            zero = bytes([ord('0')])
            # create list of zeros with size (NumberOfBytesWanted - LengthOfCurrentBytes))
            pre = [zero] * (numChars - len(blist))
            # concatenate zeros list to remaining bytes
            post = pre + blist
        # if the number of bytes is greater that requested, keep the lowest bytes, remove the overflow 
        elif (len(blist) > numChars) : 
            # get minimum index of bytes to keep
            min = len(blist) - numChars
            # get indeces from min to end of list 
            post = blist[min:]
        # if the number of bytes is equal to that requested, keep the all the bytes, change nothing
        else : 
            post = blist

        # initialize message to first byte in 'post'
        msg = post[0]
        for i in range(numChars-1) : 
            # concatenate next byte to end of the message 
            msg = msg + post[i+1]

        # return a byte message of a desired size 
        return(msg)


    @staticmethod
    def AsciiBytesToInt(msg_b: bytes, signed:bool=False) -> int :
        """Converts a ASCII-encoded bytes message into an integer.  It does this using a base-16 conversion. If the message is signed and the msb is '1', the integer will be converted to it's negative 2's complement. 

        Args:
            msg_b (bytes): Bytes message to be converted to an integer. The bytes must be base-16 or the conversion will fail. 
            signed (bool, optional): True if the message is signed, false if unsigned. Defaults to False.

        Returns:
            int: Integer result from the ASCII-encoded byte conversion.
        """
        # convert bytes to str and remove byte wrap (b'XXXX' --> XXXX)
        msg_str = str(msg_b) [2 : len(str(msg_b))-1]
        # convert string into base 16 int (reads string as hex number, returns decimal int)
        msg_int = int(msg_str,16)
        # get 2C if signed and msb is '1' 
        if(signed) : 
            nbits = len(msg_str) * 4 
            msb = msg_int >> (nbits-1) # shift out all bits except msb
            if(msb != 0) : 
                msg_int = POD_Packets.TwosComplement(msg_int,nbits)
        # return int
        return(msg_int)
    

    @staticmethod
    def BinaryBytesToInt(msg: bytes, byteorder:str='big', signed:bool=False) -> int :
        """Converts binary-encoded bytes into an integer.

        Args:
            msg (bytes): Bytes message holding binary information to be converted into an integer.
            byteorder (str, optional): Ordering of bytes. 'big' for big endian and 'little' for little endian. Defaults to 'big'.
            signed (bool, optional): Boolean flag to mark if the msg is signed (True) or unsigned (False). Defaults to False.

        Returns:
            int: Integer result from the binary-encoded bytes message.
        """
        # convert a binary message represented by bytes into an integer
        return(int.from_bytes(msg,byteorder=byteorder,signed=signed))

    
    @staticmethod
    def ASCIIbytesToInt_Split(msg: bytes, keepTopBits: int, cutBottomBits: int) -> int : 
        """Converts a specific bit range in an ASCII-encoded bytes object to an integer.

        Args:
            msg (bytes): Bytes message holding binary information to be converted into an integer.
            keepTopBits (int): Integer position of the msb of desired bit range.
            cutBottomBits (int): Integer number of lsb to remove.

        Returns:
            int: Integer result from the ASCII-encoded bytes message in a given bit range.
        """
        # mask out upper bits using 2^n - 1 = 0b1...1 of n bits. Then shift right to remove lowest bits
        return( ( POD_Packets.AsciiBytesToInt(msg) & (2**keepTopBits - 1) ) >> cutBottomBits)
    
    
    @staticmethod
    def BinaryBytesToInt_Split(msg: bytes, keepTopBits: int, cutBottomBits: int, byteorder:str='big', signed:bool=False) -> int : 
        """Converts a specific bit range in a binary-encoded bytes object to an integer.

        Args:
            msg (bytes): Bytes message holding binary information to be converted into an integer.
            keepTopBits (int): Integer position of the msb of desired bit range.
            cutBottomBits (int): Integer number of lsb to remove.
            byteorder (str, optional): Ordering of bytes. 'big' for big endian and 'little' for little endian. Defaults to 'big'.
            signed (bool, optional): Boolean flag to mark if the msg is signed (True) or unsigned (False). Defaults to False.

        Returns:
            int: Integer result from the binary-encoded bytes message in a given bit range.
        """
        # mask out upper bits using 2^n - 1 = 0b1...1 of n bits. Then shift right to remove lowest bits
        return( ( POD_Packets.BinaryBytesToInt(msg,byteorder,signed) & (2**keepTopBits - 1) ) >> cutBottomBits)


    # ------------ BUILD PACKET ------------             ------------------------------------------------------------------------------------------------------------------------
 

    @staticmethod
    def Checksum(bytesIn: bytes) -> bytes:
        """Calculates the checksum of a given bytes message. This is achieved by summing each byte in the message, 
        inverting, and taking the last byte.

        Args:
            bytesIn (bytes): Bytes message containing POD packet data.

        Returns:
            bytes: Two ASCII-encoded bytes containing the checksum for bytesIn.
        """
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
    def BuildPODpacket_Standard(commandNumber: int, payload:bytes|None=None) -> bytes : 
        """Builds a standard POD packet as bytes: 
        STX (1 byte) + command number (4 bytes) + optional packet (? bytes) + checksum (2 bytes) + ETX (1 bytes)

        Args:
            commandNumber (int): Integer representing the command number. This will be converted into a 4 byte long ASCII-encoded bytes string.
            payload (bytes | None, optional): bytes string containing the payload. Defaults to None.

        Returns:
            bytes: Bytes string of a complete standard POD packet.
        """
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

    
    @staticmethod
    def PayloadToBytes(payload: int|bytes|tuple[int|bytes], argSizes: tuple[int]) -> bytes :
        """Converts a payload into a bytes string.

        Args:
            payload (int | bytes | tuple[int | bytes]): Integer, bytes, or tuple containing the payload.
            argSizes (tuple[int]): Tuple of the argument sizes.

        Raises:
            Exception: Payload requires multiple arguments, use a tuple.
            Exception: Payload is the wrong size.
            Exception: Payload has an incorrect number of items.
            Exception: Payload has invalid values.
            Exception: Payload is an invalid type.

        Returns:
            bytes: _description_
        """
        # if integer payload is given ... 
        if(isinstance(payload,int)):
            # check that command only uses one argument 
            if( len(argSizes)!=1) : 
                raise Exception('Payload requires multiple arguments, use a tuple.')
            # convert to bytes of the expected length 
            pld = POD_Packets.IntToAsciiBytes(payload,sum(argSizes))

        # if bytes payload is given...
        elif(isinstance(payload, bytes)):
            # throw error if payload is the wrong size  
            if( len(payload) != sum(argSizes)) : # each byte is 2 hex characters
                raise Exception('Payload is the wrong size.')
            # otherwise, accept payload as given. 
            else:
                pld = payload

        # if tuple payload is given...
        elif(isinstance(payload, tuple)):
            # check that there are the correct number of arguments
            if(len(payload) != len(argSizes)) : 
                raise Exception('Payload has an incorrect number of items.')
            # build list of bytes payload parts 
            tempPld = [None]*len(payload)
            for i in range(len(payload)) : 
                if(isinstance(payload[i], int)) :
                    # convert to bytes of the expected length 
                    tempPld[i] = POD_Packets.IntToAsciiBytes(payload[i],argSizes[i])
                elif(isinstance(payload[i], bytes) and len(payload[i])==argSizes[i]): # each byte is 2 hex characters
                    # accept bytes payload as given
                    tempPld[i] = payload[i]
                else:
                    raise Exception('Payload has invalid values.')
            # concatenate list items
            pld = tempPld[0]
            for i in range(len(tempPld)-1):
                pld += tempPld[i+1]

        # bad type given 
        else :
            raise Exception('Payload is an invalid type.')

        # return payload as bytes
        return(pld)
            