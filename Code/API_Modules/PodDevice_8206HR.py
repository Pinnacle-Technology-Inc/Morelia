

# local imports 
from BasicPodProtocol       import POD_Basics
from PodPacketHandling      import POD_Packets
from PodCommands            import POD_Commands

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class POD_8206HR(POD_Basics) : 
    """
    POD_8206HR handles communication using an 8206HR POD device. 
    
    Attributes:
        _preampGain (int): Instance-level integer (10 or 100) preamplifier gain.
    """

    # ============ GLOBAL CONSTANTS ============    ========================================================================================================================


    __B4LENGTH : int = 16
    """Class-level integer representing the number of bytes for a Binary 4 packet.
    """

    __B4BINARYLENGTH : int = __B4LENGTH - 8 # length minus STX(1), command number(4), checksum(2), ETX(1) || 16 - 8 = 8
    """Class-level integer representing the number of binary bytes for a \
    Binary 4 packet.
    """

    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self, port: str|int, preampGain: int, baudrate:int=9600) -> None :
        """Runs when an instance is constructed. It runs the parent's initialization. Then it updates \
            the _commands to contain the appropriate commands for an 8206-HR POD device. 

        Args:
            port (str | int): Serial port to be opened. Used when initializing the COM_io instance.
            preampGain (int): Preamplifier gain. Must be 10 or 100.
            baudrate (int, optional): Integer baud rate of the opened serial port. Used when initializing \
                the COM_io instance. Defaults to 9600.

        Raises:
            Exception: Preamplifier gain must be 10 or 100.
        """
        # initialize POD_Basics
        super().__init__(port, baudrate=baudrate) 
        # get constants for adding commands 
        U8  = POD_Commands.U8()
        U16 = POD_Commands.U16()
        B4  = POD_8206HR.__B4BINARYLENGTH
        # remove unimplemented commands 
        self._commands.RemoveCommand(5)  # STATUS
        self._commands.RemoveCommand(9)  # ID
        self._commands.RemoveCommand(10) # SAMPLE RATE
        self._commands.RemoveCommand(11) # BINARY
        # add device specific commands
        self._commands.AddCommand(100, 'GET SAMPLE RATE',      (0,),       (U16,),    False,   'Gets the current sample rate of the system, in Hz.')
        self._commands.AddCommand(101, 'SET SAMPLE RATE',      (U16,),     (0,),      False,   'Sets the sample rate of the system, in Hz. Valid values are 100 - 2000 currently.')
        self._commands.AddCommand(102, 'GET LOWPASS',          (U8,),      (U16,),    False,   'Gets the lowpass filter for the desired channel (0 = EEG1, 1 = EEG2, 2 = EEG3/EMG). Returns the value in Hz.')
        self._commands.AddCommand(103, 'SET LOWPASS',          (U8,U16),   (0,),      False,   'Sets the lowpass filter for the desired channel (0 = EEG1, 1 = EEG2, 2 = EEG3/EMG) to the desired value (11 - 500) in Hz.')
        self._commands.AddCommand(104, 'SET TTL OUT',          (U8,U8),    (0,),      False,   'Sets the selected TTL pin (0,1,2,3) to an output and sets the value (0-1).')
        self._commands.AddCommand(105, 'GET TTL IN',           (U8,),      (U8,),     False,   'Sets the selected TTL pin (0,1,2,3) to an input and returns the value (0-1).')
        self._commands.AddCommand(106, 'GET TTL PORT',         (0,),       (U8,),     False,   'Gets the value of the entire TTL port as a byte. Does not modify pin direction.')
        self._commands.AddCommand(107, 'GET FILTER CONFIG',    (0,),       (U8,),     False,   'Gets the hardware filter configuration. 0=SL, 1=SE (Both 40/40/100Hz lowpass), 2 = SE3 (40/40/40Hz lowpas).')
        self._commands.AddCommand(180, 'BINARY4 DATA ',        (0,),       (B4,),     True,    'Binary4 data packets, enabled by using the STREAM command with a \'1\' argument.') # see _Read_Binary()
        # preamplifier gain (should be 10x or 100x)
        if(preampGain != 10 and preampGain != 100):
            raise Exception('[!] Preamplifier gain must be 10 or 100.')
        self._preampGain : int = preampGain 


    # ============ PUBLIC METHODS ============      ========================================================================================================================
    

    # ------------ OVERWRITE ------------           ------------------------------------------------------------------------------------------------------------------------


    @staticmethod
    def UnpackPODpacket_Binary(msg: bytes) -> dict[str,bytes] :
        """Overwrites the parent's method. Separates the components of a binary4 packet into a dictionary.

        Args:
            msg (bytes): Bytes string containing a complete binary4 Pod packet:  STX (1 byte)  \
                + command (4 bytes) + packet number (1 bytes) + TTL (1 byte) + ch0 (2 bytes) \
                + ch1 (2 bytes) + ch2 (2 bytes) + checksum (2 bytes) + ETX (1 byte).

        Raises:
            Exception: (1) the packet does not have the minimum number of bytes, (2) does not begin \
                with STX, or (3) does not end with ETX.

        Returns:
            dict[str,bytes]: A dictionary containing 'Command Number', 'Packet #', 'TTL', 'Ch0', 'Ch1', \
                and 'Ch2' in bytes.
        """
        # Binary 4 format = 
        #   STX (1 byte) + command (4 bytes) + packet number (1 bytes) + TTL (1 byte) 
        #   + ch0 (2 bytes) + ch1 (2 bytes) + ch2 (2 bytes) + checksum (2 bytes) + ETX (1 byte)
        MINBYTES = POD_8206HR.__B4LENGTH

        # get number of bytes in message
        packetBytes = len(msg)

        # message must have enough bytes, start with STX, or end with ETX
        if(    (packetBytes != MINBYTES)
            or (msg[0].to_bytes(1,'big') != POD_Packets.STX()) 
            or (msg[packetBytes-1].to_bytes(1,'big') != POD_Packets.ETX())
        ) : 
            raise Exception('Cannot unpack an invalid POD packet.')

        # create dict and separate message parts
        msg_unpacked = {
            'Command Number'    : msg[1:5],
            'Packet #'          : msg[5].to_bytes(1,'big'),
            'TTL'               : msg[6].to_bytes(1,'big'),
            'Ch0'               : msg[7:9],
            'Ch1'               : msg[9:11],
            'Ch2'               : msg[11:13]
            }
        
        # return unpacked POD command
        return(msg_unpacked)


    def TranslatePODpacket_Binary(self, msg: bytes) -> dict[str,int|float|dict[str,int]] : 
        """Overwrites the parent's method. Unpacks the binary4 POD packet and converts the values of the \
        ASCII-encoded bytes into integer values and the values of binary-encoded bytes into integers. \
        Channel values are given in Volts.

        Args:
            msg (bytes): Bytes string containing a complete binary4 Pod packet:  STX (1 byte) \
                + command (4 bytes) + packet number (1 bytes) + TTL (1 byte) + ch0 (2 bytes) \
                + ch1 (2 bytes) + ch2 (2 bytes) + checksum (2 bytes) + ETX (1 byte).

        Returns:
            dict[str,int|float|dict[str,int]]: A dictionary containing 'Command Number', 'Packet #', \
            'TTL', 'Ch0', 'Ch1', and 'Ch2' as numbers.
        """
        # unpack parts of POD packet into dict
        msgDict = POD_8206HR.UnpackPODpacket_Binary(msg)
        # translate the binary ascii encoding into a readable integer
        msgDictTrans = {
            'Command Number'  : POD_Packets.AsciiBytesToInt(msgDict['Command Number']),
            'Packet #'        : POD_Packets.BinaryBytesToInt(msgDict['Packet #']),
            'TTL'             : self._TranslateTTLbyte_Binary(msgDict['TTL']),
            'Ch0'             : self._BinaryBytesToVoltage(msgDict['Ch0']),
            'Ch1'             : self._BinaryBytesToVoltage(msgDict['Ch1']),
            'Ch2'             : self._BinaryBytesToVoltage(msgDict['Ch2'])
        }
        # return translated unpacked POD packet 
        return(msgDictTrans)


    def TranslatePODpacket(self, msg: bytes) -> dict[str,int|dict[str,int]] : 
        """Overwrites the parent's method. Determines if the packet is standard or binary, and \
        translates accordingly. Adds a check for the 'GET TTL PORT' command.

        Args:
            msg (bytes): Bytes string containing either a standard or binary packet.

        Returns:
            dict[str,int|dict[str,int]]: A dictionary containing the unpacked message in numbers.
        """
        # get command number (same for standard and binary packets)
        cmd = POD_Packets.AsciiBytesToInt(msg[1:5]) 
        if(self._commands.IsCommandBinary(cmd)): # message is binary 
            return(self.TranslatePODpacket_Binary(msg))
        elif(cmd == 106) : # 106, 'GET TTL PORT'
            msgDict = POD_Basics.UnpackPODpacket_Standard(msg)
            return( {
                'Command Number'    : POD_Packets.AsciiBytesToInt(msgDict['Command Number']),
                'Payload'           : self._TranslateTTLbyte_ASCII(msgDict['Payload']) # TranslatePODpacket_Standard does not handle TTL well
            } )
        else: # standard packet 
            return(self.TranslatePODpacket_Standard(msg))
            


    # ============ PROTECTED METHODS ============      ========================================================================================================================

    
    # ------------ CONVERSIONS ------------           ------------------------------------------------------------------------------------------------------------------------


    @staticmethod
    def _TranslateTTLbyte_ASCII(ttlByte: bytes) -> dict[str,int] : 
        """Separates the bits of each TTL (0-3) from a ASCII encoded byte.

        Args:
            ttlByte (bytes): One byte string for the TTL (ASCII encoded).

        Returns:
            dict[str,int]: Dictionary of the TTLs. Values are 1 when input, 0 when output.
        """
        # TTL : b 0123 XXXX <-- 8 bits, lowest 4 are always 0 (dont care=X), msb is TTL0
        return( {
            'TTL1' : POD_Packets.ASCIIbytesToInt_Split(ttlByte, 8, 7), # TTL 0 
            'TTL2' : POD_Packets.ASCIIbytesToInt_Split(ttlByte, 7, 6), # TTL 1 
            'TTL3' : POD_Packets.ASCIIbytesToInt_Split(ttlByte, 6, 5), # TTL 2 
            'TTL4' : POD_Packets.ASCIIbytesToInt_Split(ttlByte, 5, 4)  # TTL 3 
        } )   
    

    @staticmethod
    def _TranslateTTLbyte_Binary(ttlByte: bytes) -> dict[str,int] : 
        """Separates the bits of each TTL (0-3) from a binary encoded byte.

        Args:
            ttlByte (bytes): One byte string for the TTL (binary encoded).

        Returns:
            dict[str,int]: Dictionary of the TTLs. Values are 1 when input, 0 when output.
        """
        # TTL : b 0123 XXXX <-- 8 bits, lowest 4 are always 0 (dont care=X), msb is TTL0
        return( {
            'TTL1' : POD_Packets.BinaryBytesToInt_Split(ttlByte, 8, 7), # TTL 0 
            'TTL2' : POD_Packets.BinaryBytesToInt_Split(ttlByte, 7, 6), # TTL 1 
            'TTL3' : POD_Packets.BinaryBytesToInt_Split(ttlByte, 6, 5), # TTL 2 
            'TTL4' : POD_Packets.BinaryBytesToInt_Split(ttlByte, 5, 4)  # TTL 3 
        } )   


    def _BinaryBytesToVoltage(self, value: bytes) -> float :
        """Converts a binary bytes value read from POD device and converts it to the real voltage value \
        at the preamplifier input.

        Args:
            value (bytes): Bytes string containing voltage measurement.

        Returns:
            float: A number containing the voltage in Volts [V].
        """
        # convert binary message from POD to integer
        value_int = POD_Packets.BinaryBytesToInt(value, byteorder='little')
        # calculate voltage 
        voltageADC = ( value_int / 65535.0 ) * 4.096 # V
        totalGain = self._preampGain * 50.2918
        realValue = ( voltageADC - 2.048 ) / totalGain
        # return the real value at input to preamplifier 
        return(realValue) # V 


    # ------------ OVERWRITE ------------           ------------------------------------------------------------------------------------------------------------------------


    def _Read_Binary(self, prePacket: bytes, validateChecksum:bool=True) -> bytes :
        """After receiving the prePacket, it reads the 8 bytes(TTL+channels) and then reads to ETX \
        (checksum+ETX). 

        Args:
            prePacket (bytes): Bytes string containing the beginning of a POD packet: STX (1 byte) \
                + command number (4 bytes).
            validateChecksum (bool, optional): Set to True to validate the checksum. Set to False to \
                skip validation. Defaults to True.

        Raises:
            Exception: Bad checksum for binary POD packet read.

        Returns:
            bytes: Byte string for a binary4 POD packet.
        """

        # ------------------------------------------------------------		
        # Binary 4 Data Format
        # ------------------------------------------------------------		
        # Byte    Value	        Format      Description 
        # ------------------------------------------------------------		
        # 0	    0x02	        Binary		STX
        # 1	    0	            ASCII		Command Number Byte 0
        # 2	    0	            ASCII		Command Number Byte 1
        # 3	    B	            ASCII		Command Number Byte 2
        # 4	    4	            ASCII		Command Number Byte 3
        # 5	    Packet Number 	Binary		A rolling value that increases with each packet, and rolls over to 0 after it hits 255
        # 6	    TTL	            Binary		The byte value of the TTL port.  Value would be equivalent to the command 106 GET TTL PORT above
        # 7	    Ch0 LSB	        Binary		Least significant byte of the Channel 0 (EEG1) value
        # 8	    Ch0 MSB	        Binary		Most significant byte of the Channel 0 (EEG1) value
        # 9	    Ch1 LSB	        Binary		Channel 1 / EEG2 LSB
        # 10    Ch1 MSB	        Binary		Channel 1 / EEG2 MSB
        # 11    Ch2 LSB	        Binary		Channel 2 / EEG3/EMG LSB
        # 12    Ch2 MSB	        Binary		Channel 2 / EEG3/EMG MSB
        # 13    Checksum MSB	ASCII		MSB of checksum
        # 14    Checksum LSB	ASCII		LSB of checkxum
        # 15    0x03	        Binary		ETX
        # ------------------------------------------------------------
        
        # get prepacket + packet number, TTL, and binary ch0-2 (these are all binary, do not search for STX/ETX) + read csm and ETX (3 bytes) (these are ASCII, so check for STX/ETX)
        packet = prePacket + self._port.Read(self.__B4BINARYLENGTH) + self._Read_ToETX(validateChecksum=validateChecksum)
        # check if checksum is correct 
        if(validateChecksum):
            if(not self._ValidateChecksum(packet) ) :
                raise Exception('Bad checksum for binary POD packet read.')
        # return complete variable length binary packet
        return(packet)