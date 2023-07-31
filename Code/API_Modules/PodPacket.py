# enviornment imports
from typing import Any
from collections.abc import Callable

# local imports
from PodPacketHandling  import POD_Packets
from PodCommands        import POD_Commands

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

# ==========================================================================================================

class Packet : 
    """Container class that stores a command packet for a POD device. The format is \
    STX (1 byte) + command number (4 bytes) + data (? bytes) + ETX (1 byte).
    
    Attributes:
        _commands (POD_Commands | None): Available commands for a POD device. 
        rawPacket (bytes): Bytes string containing a POD packet. Should begin with \
            STX and end with ETX.
        commandNumber (bytes | None): Command number from the Pod packet.
    """
    
    def __init__(self, 
                 pkt: bytes, 
                 commands: POD_Commands|None = None
                ) -> None:
        """Sets the class instance variables. 

        Args:
            pkt (bytes): Bytes string containing a POD packet. Should begin with STX \
                and end with ETX.
            commands (POD_Commands | None, optional): Available commands for a POD device.\
                Defaults to None.
        """
        self.CheckIfPacketIsValid(pkt)
        self._commands: POD_Commands|None = commands
        self.rawPacket: bytes = bytes(pkt)
        self.commandNumber: bytes|None = self.GetCommandNumber(pkt)
        
    # ----- Packet to dictionary -----
        
    def UnpackAll(self) -> dict[str,bytes] :
        """Builds a dictionary containing all parts of the POD packet in bytes. 

        Raises:
            Exception: Nothing to unpack.

        Returns:
            dict[str,bytes]: Dictionary with the command number.
        """
        if(self.HasCommandNumber()) : 
            return { 'Command Number' : self.commandNumber }
        raise Exception('Nothing to unpack.')  
      
    def TranslateAll(self) -> dict[str, Any] :
        """Builds a dictionary containing all parts of the POD packet in readable values. 

        Raises:
            Exception: Nothing to translate.

        Returns:
            dict[str,Any]: Dictionary with the command number.
        """
        if(self.HasCommandNumber()) : 
            return { 'Command Number' : self.CommandNumber() }
        raise Exception('Nothing to translate.')  
        
    # ----- Translated parts -----

    def CommandNumber(self) -> int : 
        """Translate the binary ASCII encoding into a readable integer

        Returns:
            int: Integer of the command number.
        """
        return POD_Packets.AsciiBytesToInt(self.commandNumber)

    # ----- Get parts from packet bytes -----

    @staticmethod
    def GetCommandNumber(pkt: bytes) -> bytes|None :
        """Gets the command number bytes from a POD packet. 

        Args:
            pkt (bytes): Bytes string containing a POD packet. Should begin with STX and \
                end with ETX.

        Returns:
            bytes|None: Bytes string of the command number, if available.
        """
        if(len(pkt) > Packet.GetMinimumLength() + 4) :
            return pkt[1:5]
        return None
    
    # ----- Properties -----
    
    @staticmethod
    def GetMinimumLength() -> int : 
        """Gets the number of bytes in the smallest possible packet; STX (1 byte) + \
        something + ETX (1 byte). 

        Returns:
            int: integer representing the minimum length of a generic bytes string.
        """
        return 2
    
    @staticmethod
    def CheckIfPacketIsValid(msg: bytes) :
        """Raises an Exception if the packet is incorrectly formatted. 

        Args:
            msg (bytes):  Bytes string containing a POD packet. Should begin with STX \
                and end with ETX.

        Raises:
            Exception: Packet must begin with STX.
            Exception: Packet must end in ETX
        """
        if(msg[0].to_bytes(1,'big') != POD_Packets.STX()) :
            raise Exception('Packet must begin with STX.')
        if(msg[len(msg)-1].to_bytes(1,'big') != POD_Packets.ETX()) : 
            raise Exception('Packet must end in ETX')
    
    def HasCommands(self) -> bool:
        """Checks if the Packet instance has commands set.
        
        Returns:
            bool: True if the commands have been set, false otherwise.
        """ 
        return isinstance(self._commands, POD_Commands) 
            
    def HasCommandNumber(self) -> bool :
        """Checks if the packet has a command number.

        Returns:
            bool: True if the packet has a command number, False otherwise.
        """
        return (self.commandNumber != None)

# ==========================================================================================================


class Packet_Standard(Packet) : 
    """Container class that stores a standard command packet for a POD device. The format is \
    STX (1 byte) + command number (4 bytes) + optional payload (? bytes) + checksum (2 bytes) + ETX (1 bytes)
    
    Attributes:
        _commands (POD_Commands | None): Available commands for a POD device. 
        _customPayload (Callable[[Any],tuple]|None): Optional function to translate the payload. 
        _customPayloadArgs (Any): Optional arguments for the _customPayload.
        rawPacket (bytes): Bytes string containing a POD packet. Should begin with STX and \
            end with ETX.
        commandNumber (bytes): Command number from the packet. 
        payload (bytes): Optional payload from the packet.
    """
    
    def __init__(self, 
                 pkt: bytes, 
                 commands: POD_Commands
                ) -> None:
        """Sets the class instance variables. 

        Args:
            pkt (bytes): Bytes string containing a POD packet. Should begin with STX and \
                ending with ETX.
            commands (POD_Commands | None, optional): _description_. Defaults to None.
        """
        super().__init__(pkt,commands)
        self.payload: bytes|None = self.GetPayload(pkt)
        self._customPayload: Callable[[Any],tuple]|None = None
        self._customPayloadArgs: Any|None = None
    
    # ----- Packet to dictionary -----
        
    def UnpackAll(self) -> dict[str, bytes]:
        """Builds a dictionary containing all parts of the POD packet in bytes. 

        Returns:
            dict[str,bytes]: Dictionary with the command number and payload.
        """
        data: dict = super().UnpackAll()
        if(self.HasPayload()) : 
            data['Payload'] = self.payload
        return data
    
    def TranslateAll(self) -> dict[str, Any]:
        """Builds a dictionary containing all parts of the POD packet in readable values. 

        Returns:
            dict[str,Any]: Dictionary with the command number and payload.
        """
        data: dict =  super().TranslateAll()
        if(self.HasPayload()) : 
            data['Payload'] = self.Payload()
        return data
    
    # ----- Customization -----

    def SetCustomPayload(self, func: Callable[[Any],tuple], args: Any = None) -> None :
        """Sets a custom function with optional arguments to translate the payload.

        Args:
            func (function): Function to translate the payload.
            args (optional): Arguments . Defaults to None.
        """
        self._customPayload: Callable[[Any],tuple] = func
        self._customPayloadArgs: Any = args
        
    def HasCustomPayload(self) -> bool : 
        """Checks if a custom payload has been set.

        Returns:
            bool: True if there is a custom payload, False otherwise.
        """
        return (self._customPayload != None)
    
    # ----- Translated parts -----
    
    def Payload(self) -> tuple|None :
        """Gets the payload as a readable tuple of values. 

        Returns:
            tuple|None: Translated payload, if available.
        """
        # check for payload 
        if(not self.HasPayload()) :  return None
        if(self.HasCustomPayload()): return self._customPayload(self._customPayloadArgs)
        else:                        return self._DefaultPayload()
        
    def _DefaultPayload(self) -> tuple[int] :
        """Splits the payload up into its components and translates the binary ASCII encoding \
        into a readable integer.

        Returns:
            tuple[int]: Tuple with integer values for each component of the payload.
        """
        # get format of payload 
        useSizes: tuple[int] = (len(self.payload),)
        if(self.HasCommands()) : 
            cmd = self.CommandNumber()
            argSizes: tuple[int] = self._commands.ArgumentHexChar(cmd)
            retSizes: tuple[int] = self._commands.ReturnHexChar(cmd)
            # override which size tuple to use
            if(  sum(useSizes) == sum(argSizes)) : useSizes = argSizes
            elif(sum(useSizes) == sum(retSizes)) : useSizes = retSizes
        # split up payload using tuple of sizes 
        pldSplit = [None]*len(useSizes)
        startByte = 0
        for i in range(len(useSizes)) : 
            endByte = startByte + useSizes[i] # count to stop byte
            pldSplit[i] = POD_Packets.AsciiBytesToInt(self.payload[startByte:endByte]) # get bytes 
            startByte = endByte # get new start byte
        return tuple(pldSplit) 
    
    # ----- Get parts from packet bytes -----
    
    @staticmethod
    def GetPayload(pkt: bytes) -> bytes|None :
        """Gets the payload from a POD packet, if available.

        Args:
            pkt (bytes): Bytes string containing a POD packet.

        Returns:
            bytes|None: Bytes string of the payload, if available.
        """
        if( (len(pkt) - Packet_Standard.GetMinimumLength()) > 0) :
            return pkt[5:(len(pkt)-3)]
        return None
    
    # ----- Properties -----

    def HasPayload(self) -> bool : 
        """Checks if this Packet_Standard instance has a payload. 

        Returns:
            bool: True if there is a payload, false otherwise.
        """
        return( self.payload != None )
    
    @staticmethod
    def GetMinimumLength() -> int : 
        """Gets the number of bytes in the smallest possible packet. 
        
        Returns:
            int: integer representing the minimum length of a standard \
                POD command packet. Format is STX (1 byte) + command number (4 bytes) \
                + optional packet (? bytes) + checksum (2 bytes) + ETX (1 bytes)
        """
        return 8
    
    @staticmethod   
    def CheckIfPacketIsValid(msg: bytes) :
        """Raises an Exception if the packet is incorrectly formatted. 

        Args:
            msg (bytes):  Bytes string containing a POD packet. Should begin with STX and \
                end with ETX.

        Raises:
            Exception: Packet is too small to be a standard packet.
        """
        Packet.CheckIfPacketIsValid(msg)    
        if(len(msg) < Packet_Standard.GetMinimumLength()) : 
            raise Exception('Packet is too small to be a standard packet.')
        

# ==========================================================================================================


class Packet_BinaryStandard(Packet) :     
    """Container class that stores a standard binary command packet for a POD device. The format is \
    STX (1 byte) + command number (4 bytes) + length of binary (4 bytes) + checksum (2 bytes) \
    + ETX (1 bytes) + binary (LENGTH bytes) + checksum (2 bytes) + ETX (1 bytes) 
    
    Attributes:
        _commands (POD_Commands | None): Available commands for a POD device. 
        rawPacket (bytes): Bytes string containing a POD packet. Should begin with STX \
            and end with ETX.
        binaryLength (bytes): Number of bytes of binary data from the packet.
        binaryData (bytes): Variable length binary datafrom the packet.
    """

    def __init__(self, 
                 pkt: bytes, 
                 commands: POD_Commands | None = None
                ) -> None:
        """Sets the class instance variables. 

        Args:
            pkt (bytes): Bytes string containing a POD packet. Should begin with STX and \
                ending with ETX.
            commands (POD_Commands | None, optional): Available commands for a POD device. \
                Defaults to None.
        """       
        super().__init__(pkt, commands)
        self.binaryLength:  bytes = Packet_BinaryStandard.GetBinaryLength(pkt),
        self.binaryData:    bytes = Packet_BinaryStandard.GetBinaryData(pkt)
       
    # ----- Packet to dictionary -----
 
    def UnpackAll(self) -> dict[str, bytes]:
        """Builds a dictionary containing all parts of the POD packet in bytes. 

        Returns:
            dict[str,bytes]: Dictionary with the command number, binary packet length, \
                and binary data.
        """
        data: dict = super().UnpackAll()
        data['Binary Packet Length'] = self.binaryLength
        data['Binary Data']          = self.binaryData
        return data
        
    def TranslateAll(self) -> dict[str, Any]:
        """Builds a dictionary containing all parts of the POD packet in readable values. 

        Returns:
            dict[str,Any]: Dictionary with the command number, binary packet length, \
                and binary data.
        """
        data: dict =  super().TranslateAll()
        data['Binary Packet Length'] = self.BinaryLength()
        data['Binary Data']          = self.binaryData
        return data
        
    # ----- Translated parts -----

    def BinaryLength(self) -> int : 
        """Translate the binary ASCII encoding of the binary data length \
        into a readable integer

        Returns:
            int: Integer of the binary data length.
        """
        return POD_Packets.AsciiBytesToInt(self.binaryLength)

    # ----- Get parts from packet bytes -----

    @staticmethod
    def GetBinaryLength(pkt: bytes) -> bytes : 
        """Gets the length, or number of bytes, of the binary data in a POD packet.

        Args:
            pkt (bytes): Bytes string containing a POD packet.

        Returns:
            bytes: Bytes string of the length of the binary data.
        """
        return pkt[5:9] # 4 bytes after command number
    
    def GetBinaryData(pkt: bytes) -> bytes : 
        """Gets the binary data from a POD packet.

        Args:
            pkt (bytes): Bytes string containing a POD packet.

        Returns:
            bytes: Bytes string containg binary data.
        """
        return pkt[12:(len(pkt)-3)] # bytes after 1st ETX
                
    # ----- Properties -----

    @staticmethod
    def GetMinimumLength() -> int : 
        """Gets the number of bytes in the smallest possible packet; \
        STX (1 byte) + something + ETX (1 byte). 

        Returns:
            int: integer representing the minimum length of a binary POD \
                command packet. Format is STX (1 byte) + command number (4 bytes) + length \
                of binary (4 bytes) + checksum (2 bytes) + ETX (1 bytes) + binary (LENGTH \
                bytes) + checksum (2 bytes) + ETX (1 bytes)
        """
        return 15
    
    @staticmethod   
    def CheckIfPacketIsValid(msg: bytes) :
        """Raises an Exception if the packet is incorrectly formatted. 

        Args:
            msg (bytes):  Bytes string containing a POD packet. Should begin with STX \
                and end with ETX.

        Raises:
            Exception: Packet is too small to be a standard packet.
            Exception: A standard binary packet must have an ETX before the binary bytes.
        """
        Packet.CheckIfPacketIsValid(msg) 
        if(len(msg) < Packet_BinaryStandard.GetMinimumLength()) : 
            raise Exception('Packet is too small to be a standard binary packet.')
        if(msg[11].to_bytes(1,'big') != POD_Packets.ETX()) : 
            raise Exception('A standard binary packet must have an ETX before the binary bytes.')
        
        
# ==========================================================================================================


class Packet_Binary4(Packet) : 
    """Container class that stores a binary command packet for a POD device. The format is \
    STX (1 byte) + command (4 bytes) + packet number (1 byte) + TTL (1 byte) + \
    CH0 (2 bytes) + CH1 (2 bytes) + CH2 (2 bytes) + checksum (2 bytes) + ETX (1 byte). 

    Attributes:
        _commands (POD_Commands | None): Available commands for a POD device. 
        _preampGain (int): Preamplifier gain. This should be 10 or 100 for an 8206-HR device.
        rawPacket (bytes): Bytes string containing a POD packet. Should begin with STX \
            and end with ETX.
        packetNumber (bytes): Packet number for this POD packet.
        ttl (bytes): TTL data for this packet.
        ch0 (bytes): channel 0 data for this packet.
        ch1 (bytes): channel 1 data for this packet.
        ch2 (bytes): channel 2 data for this packet.
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
    # 13    Checksum MSB    ASCII		MSB of checksum
    # 14    Checksum LSB    ASCII		LSB of checksum
    # 15    0x03            Binary		ETX
    # ------------------------------------------------------------
    
    def __init__(self, 
                 pkt: bytes, 
                 preampGain: int, 
                 commands: POD_Commands | None = None
                ) -> None:
        """Sets the class instance variables. 

        Args:
            pkt (bytes): Bytes string containing a POD packet. Should begin with STX and \
                ending with ETX.
            preampGain (int): Preamplifier gain. This is 10 or 100 for an 8206-HR device.
            commands (POD_Commands | None, optional): Available commands for a POD device. Defaults to None.
        """
        super().__init__(pkt, commands)
        self.packetNumber: bytes = self.GetPacketNumber(pkt)
        self.ttl: bytes = self.GetTTL(pkt)
        self.ch0: bytes = self.GetCh(0,pkt)
        self.ch1: bytes = self.GetCh(1,pkt)
        self.ch2: bytes = self.GetCh(2,pkt)
        self._preampGain: int = int(preampGain)

    # ----- Packet to dictionary -----

    def UnpackAll(self) -> dict[str, bytes]:
        """Builds a dictionary containing all parts of the POD packet in bytes. 

        Returns:
            dict[str,bytes]: Dictionary with the command number, packet number, TTL \
                and channels 0, 1, and 2.
        """
        data: dict = super().UnpackAll()
        data['Packet #'] = self.packetNumber
        data['TTL'] = self.ttl
        data['Ch0'] = self.ch0
        data['Ch1'] = self.ch1
        data['Ch2'] = self.ch2  
        return data

    def TranslateAll(self) -> dict[str, Any]:
        """Builds a dictionary containing all parts of the POD packet in readable values. 

        Returns:
            dict[str, Any]: Dictionary with the command number, packet number, TTL \
                and channels 0, 1, and 2.
        """
        data: dict = super().TranslateAll()
        data['Packet #'] = self.PacketNumber()
        data['TTL'] = self.Ttl() 
        data['Ch0'] = self.ch0
        data['Ch1'] = self.ch1
        data['Ch2'] = self.ch2
        return data
    
    # ----- Translated parts -----
    
    def PacketNumber(self) -> int : 
        """Translates the binary packet number into a readable integer.

        Returns:
            int: Integer of the packet number.
        """
        return POD_Packets.BinaryBytesToInt(self.packetNumber)
    
    def Ttl(self) -> dict[str,int] : 
        """Translates the binary TTL bytes into a dictionary containing each TTL value.

        Returns:
            dict[str,int]: Dictionary with TTL name keys and TTL data as values.
        """
        return Packet_Binary4.TranslateBinaryTTLbyte(self.ttl)

    def Ch(self, n: int) -> float :
        """Translates the binary channel n bytes into a voltage.

        Args:
            n (int): Channel number. Should be 0, 1, or 2.

        Raises:
            Exception: Channel does not exist.

        Returns:
            float: Voltage of channel n in Volts.
        """
        match n :
            case 0 : ch = self.ch0
            case 1 : ch = self.ch1
            case 2 : ch = self.ch2
            case _ : raise Exception('Channel '+str(n)+' does not exist.')
        return Packet_Binary4.BinaryBytesToVoltage(ch, self._preampGain)

    # ----- Get parts from packet bytes -----

    @staticmethod
    def GetPacketNumber(pkt: bytes) -> bytes : 
        """Gets the packet number in bytes from a POD packet.

        Args:
            pkt (bytes): Bytes string containing a POD packet. Should begin with STX and \
                end with ETX.

        Returns:
            bytes: Bytes string of the packet number.
        """
        return pkt[5].to_bytes(1,'big')

    @staticmethod
    def GetTTL(pkt: bytes) -> bytes : 
        """Gets the TTL bytes from a POD packet

        Args:
            pkt (bytes): Bytes string containing a POD packet. Should begin with STX and \
                end with ETX.

        Returns:
            bytes: Bytes string of the TTL data.
        """
        return pkt[6].to_bytes(1,'big')

    @staticmethod
    def GetCh(n: int, pkt: bytes) -> bytes : 
        """Gets the channel n bytes from a POD packet. 

        Args:
            n (int): Channel number. Should be 0, 1, or 2.
            pkt (bytes): Bytes string containing a POD packet. Should begin with STX and \
                end with ETX.

        Returns:
            bytes: Bytes string of the channel 0 data.

        Returns:
            bytes: Channel does not exist.
        """
        match n : 
            case 0 : return pkt[7:9]
            case 1 : return pkt[9:11]
            case 2 : return pkt[11:13]
            case _ : raise Exception('Channel '+str(n)+' does not exist.')

    # ----- Properties -----

    @staticmethod
    def GetMinimumLength() -> int : 
        """Gets the number of bytes in the smallest possible binary4 packet; \
        STX (1 byte) + command (4 bytes) + packet number (1 byte) + TTL (1 byte) + \
        CH0 (2 bytes) + CH1 (2 bytes) + CH2 (2 bytes) + checksum (2 bytes) + ETX (1 byte). 

        Returns:
            int: integer representing the minimum length of a binary4 POD packet. 
        """
        return 16

    @staticmethod
    def GetBinaryLength() -> int :
        """Gets the number of bytes of binary data in a binary4 packet.

        Returns:
            int: Integer representing the number of binary encoded bytes in a binary4 packet.
        """
        # length minus STX(1), command number(4), checksum(2), ETX(1) || 16 - 8 = 8
        return( Packet_Binary4.GetMinimumLength() - 8 )

    @staticmethod   
    def CheckIfPacketIsValid(msg: bytes) :
        """Raises an Exception if the packet is incorrectly formatted. 

        Args:
            msg (bytes):  Bytes string containing a POD packet. Should begin with STX \
                and end with ETX.

        Raises:
            Exception: Packet the wrong size to be a binary4 packet.
        """
        Packet.CheckIfPacketIsValid(msg) 
        if(len(msg) != Packet_Binary4.GetMinimumLength()) : 
            raise Exception('Packet the wrong size to be a binary4 packet.')

    # ----- Conversions -----

    @staticmethod
    def TranslateBinaryTTLbyte(ttlByte: bytes) -> dict[str,int] : 
        """Separates the bits of each TTL (0-3) from a binary encoded byte.

        Args:
            ttlByte (bytes): One byte string for the TTL (binary encoded).

        Returns:
            dict[str,int]: Dictionary of the TTLs. Values are 1 when input, 0 when output.
        """
        # TTL : b 0123 XXXX <-- 8 bits, lowest 4 are always 0 (dont care=X), msb is TTL0
        return {
            'TTL1' : POD_Packets.BinaryBytesToInt_Split(ttlByte, 8, 7), # TTL 0 
            'TTL2' : POD_Packets.BinaryBytesToInt_Split(ttlByte, 7, 6), # TTL 1 
            'TTL3' : POD_Packets.BinaryBytesToInt_Split(ttlByte, 6, 5), # TTL 2 
            'TTL4' : POD_Packets.BinaryBytesToInt_Split(ttlByte, 5, 4)  # TTL 3 
        } 
        
        
    @staticmethod
    def BinaryBytesToVoltage(value: bytes, preampGain: int) -> float :
        """Converts a binary bytes value read from POD device and converts it to the \
        real voltage value at the preamplifier input.

        Args:
            value (bytes): Bytes string containing voltage measurement.

        Returns:
            float: A number containing the voltage in Volts [V].
        """
        # convert binary message from POD to integer
        value_int = POD_Packets.BinaryBytesToInt(value, byteorder='little')
        # calculate voltage 
        voltageADC = ( value_int / 65535.0 ) * 4.096 # V
        totalGain = preampGain * 50.2918
        realValue = ( voltageADC - 2.048 ) / totalGain
        # return the real value at input to preamplifier 
        return realValue # V 


# ==========================================================================================================


class Packet_Binary5(Packet) : 
    
    
    # -----------------------------------------------------------------------------
        # Binary 5 Data Format
        # -----------------------------------------------------------------------------		
        # Byte    Value	                        Format      Description 
        # -----------------------------------------------------------------------------		
        # 0	    0x02	                        Binary		STX
        # 1	    0	                            ASCII		Command Number Byte 0
        # 2	    0	                            ASCII		Command Number Byte 1
        # 3	    B	                            ASCII		Command Number Byte 2
        # 4	    5	                            ASCII		Command Number Byte 3
        # 5	    Packet Number 	                Binary		A rolling value that increases with each packet, and rolls over to 0 after it hits 255
        # 6	    Status	                        Binary		Status byte, currently unused
        # 7	    CH3 17~10	                    Binary		Top 8 bits of CH3.  Data is 18 bits, packed over 3 bytes.  Because of this the number of bits in each byte belonging to each chanenl changes.  Values are sent MSB/MSb first
        # 8	    CH3 9~2	                        Binary		Middle 8 bits of CH3
        # 9	    CH3 1~0, CH2 17~12	            Binary		Bottom 2 bits of CH3 and top 6 bits of CH2
        # 10	CH2 11~4	                    Binary		Middle 8 bits of Ch2
        # 11	CH2 3~0, CH1 17~14	            Binary		Bottom 4 bits of CH2 and top 4 bits of CH1
        # 12	CH1 13~6	                    Binary		Middle 8 bits of CH1
        # 13	CH1 5~0, CH0 17~16	            Binary		Bottom 6 bits of CH1 and top 2 bits of CH0
        # 14	CH0 15~8	                    Binary		Middle 8 bits of Ch0
        # 15	CH0 7~0	                        Binary		Bottom 8 bits of CH0
        # 16	EXT0 Analog Value High Byte	    Binary		Top nibble of the 12-bit EXT0 analog value.  Sent MSB/MSb first
        # 17	EXT0 Analog Value Low Byte	    Binary		Bottom nibble of the EXT0 value
        # 18	EXT1 Analog Value High Byte	    Binary		Top nibble of the 12-bit EXT1 analog value.  Sent MSB/MSb first
        # 19	EXT1 Analog Value Low Byte	    Binary		Bottom nibble of the EXT1 value
        # 20	TTL1 Analog Value High Byte	    Binary		Top nibble of the TTL1 pin read as a 12-bit analog value
        # 21	TTL1 Analog Value Low Byte	    Binary		Bottom nibble of the TTL2 pin analog value
        # 22	TTL2 Analog Value High Byte	    Binary		Top nibble of the TTL1 pin read as a 12-bit analog value
        # 23	TTL2 Analog Value Low Byte	    Binary		Bottom nibble of the TTL2 pin analog value
        # 24	TTL3 Analog Value High Byte	    Binary		Top nibble of the TTL3 pin read as a 12-bit analog value
        # 25	TTL3 Analog Value Low Byte	    Binary		Bottom nibble of the TTL3 pin analog value
        # 26	TTL4 Analog Value High Byte	    Binary		Top nibble of the TTL4 pin read as a 12-bit analog value
        # 27	TTL4 Analog Value Low Byte	    Binary		Bottom nibble of the TTL4 pin analog value
        # 28	Checksum MSB	                ASCII		Checksum
        # 29	Checksum LSB	                ASCII		Checksum 
        # 30	0x03	                        Binary		ETX
        # -----------------------------------------------------------------------------
    
    def __init__(self, pkt: bytes,                  
                 ssGain: dict[str,int|None] = {'A':None,'B':None,'C':None,'D':None}, 
                 preampGain: dict[str,int|None] = {'A':None,'B':None,'C':None,'D':None}, 
                 commands: POD_Commands | None = None
                ) -> None:
        super().__init__(pkt, commands)
        # packet parts
        self.packetNumber   : bytes = self.GetPacketNumber(pkt)
        self.status         : bytes = self.GetStatus(pkt)
        self.channels       : bytes = self.GetChannels(pkt)
        self.aEXT0          : bytes = self.GetAnalogEXT(0, pkt)
        self.aEXT1          : bytes = self.GetAnalogEXT(1, pkt)
        self.aTTL1          : bytes = self.GetAnalogTTL(1, pkt)
        self.aTTL2          : bytes = self.GetAnalogTTL(2, pkt)
        self.aTTL3          : bytes = self.GetAnalogTTL(3, pkt)
        self.aTTL4          : bytes = self.GetAnalogTTL(4, pkt)
        # device properties 
        self._ssGain        : dict[str,int|None] = ssGain
        self._preampGain    : dict[str,int|None] = preampGain
    
    # ----- Packet to dictionary -----
    
    def UnpackAll(self) -> dict[str, bytes]:
        data: dict = super().UnpackAll()
        data['Packet #'   ] = self.packetNumber
        data['Status'     ] = self.status 
        data['Channels'   ] = self.channels
        data['Analog EXT0'] = self.aEXT0
        data['Analog EXT1'] = self.aEXT1
        data['Analog TTL1'] = self.aTTL1
        data['Analog TTL2'] = self.aTTL2
        data['Analog TTL3'] = self.aTTL3
        data['Analog TTL4'] = self.aTTL4
        return data
    
    def TranslateAll(self) -> dict[str, Any]:
        data: dict = super().UnpackAll()
        data['Packet #'   ] = self.PacketNumber()
        data['Status'     ] = self.Status()
        for c in ['A', 'B', 'C', 'D'] :   # for each channel 
            if(self._ssGain[c] != None) : # exclude no-connects 
                data[c] = self.Channel(c) # get channel voltage 
        data['Analog EXT0'] = self.AnalogEXT(0)
        data['Analog EXT1'] = self.AnalogEXT(1)
        data['Analog TTL1'] = self.AnalogTTL(1)
        data['Analog TTL2'] = self.AnalogTTL(2)
        data['Analog TTL3'] = self.AnalogTTL(3)
        data['Analog TTL4'] = self.AnalogTTL(4)
        return data

    # ----- Translated parts -----
    
    def PacketNumber(self) -> int : 
        return POD_Packets.BinaryBytesToInt(self.packetNumber)
    
    def Status(self) -> int : 
        return POD_Packets.BinaryBytesToInt(self.status)

    def Channel(self, c: str) -> float : 
        match c : 
            case 'A' : chan = POD_Packets.BinaryBytesToInt_Split(self.channels[6:9], 18, 0) #  A | 13  CH1 5~0, CH0 17~16 | 14 CH0 15~8  | 15 CH0 7~0            | --> cut top 6              bits
            case 'B' : chan = POD_Packets.BinaryBytesToInt_Split(self.channels[4:7], 20, 2) #  B | 11  CH2 3~0, CH1 17~14 | 12 CH1 13~6  | 13 CH1 5~0, CH0 17~16 | --> cut top 4 and bottom 2 bits
            case 'C' : chan = POD_Packets.BinaryBytesToInt_Split(self.channels[2:5], 22, 4) #  C |  9  CH3 1~0, CH2 17~12 | 10 CH2 11~4  | 11 CH2 3~0, CH1 17~14 | --> cut top 2 and bottom 4 bits
            case 'D' : chan = POD_Packets.BinaryBytesToInt_Split(self.channels[0:3], 24, 6) #  D |  7  CH3 17~10          |  8 CH3 9~2   |  9 CH3 1~0, CH2 17~12 | --> cut           bottom 6 bits
            case  _  : raise Exception('Channel '+str(c)+' does not exist.')
        return Packet_Binary5._Voltage_PrimaryChannels(chan, self._ssGain[c], self._preampGain[c])

    def AnalogEXT(self, n: int) -> float : 
        match n :
            case 0 : ext = self.aEXT0
            case 1 : ext = self.aEXT1
            case _ : raise Exception('AEXT'+str(n)+' does not exist.')
        return Packet_Binary5._Voltage_SecondaryChannels(POD_Packets.BinaryBytesToInt(ext))
    
    def AnalogTTL(self, n: int) -> float : 
        match n:
            case 1 : ttl = self.aTTL1
            case 2 : ttl = self.aTTL2
            case 3 : ttl = self.aTTL3
            case 4 : ttl = self.aTTL4
            case _ : raise Exception('ATTL'+str(n)+' does not exist.')
        return Packet_Binary5._Voltage_SecondaryChannels( POD_Packets.BinaryBytesToInt(ttl) )
    
    # ----- Get parts from packet bytes -----
    
    @staticmethod
    def GetPacketNumber(pkt: bytes) -> bytes : 
        return pkt[5].to_bytes(1,'big')
    
    @staticmethod
    def GetStatus(pkt: bytes) -> bytes : 
        return pkt[6].to_bytes(1,'big')

    @staticmethod
    def GetChannels(pkt: bytes) -> bytes : 
        return pkt[7:16]
    
    @staticmethod
    def GetAnalogEXT(n: int, pkt: bytes) -> bytes : 
        match n :
            case 0 : return pkt[16:18]
            case 1 : return pkt[18:20]
            case _ : raise  Exception('AEXT'+str(n)+' does not exist.')
    
    @staticmethod
    def GetAnalogTTL(n: int, pkt: bytes) -> bytes : 
        match n:
            case 1 : return pkt[20:22]
            case 2 : return pkt[22:24]
            case 3 : return pkt[24:26]
            case 4 : return pkt[26:28]
            case _ : raise  Exception('ATTL'+str(n)+' does not exist.')
        
    # ----- Properties -----
        
    @staticmethod
    def GetMinimumLength() -> int : 
        return 31
    
    @staticmethod
    def GetBinaryLength() -> int :
        # length minus STX(1), command number(4), checksum(2), ETX(1) || 31 - 8 = 23
        return Packet_Binary5.GetMinimumLength - 8

    @staticmethod   
    def CheckIfPacketIsValid(msg: bytes) :
        Packet.CheckIfPacketIsValid(msg) 
        if(len(msg) != Packet_Binary5.GetMinimumLength()) : 
            raise Exception('Packet the wrong size to be a binary5 packet.')
    
    # ----- Conversions -----

    @staticmethod
    def _Voltage_PrimaryChannels(value: int, ssGain:int|None=None, PreampGain:int|None=None) -> float :
        """Converts a value to a voltage for a primary channel. 

        Args:
            value (int): Value to be converted to voltage.
            ssGain (int | None, optional): Second stage gain. Defaults to None.
            PreampGain (int | None, optional): Preamplifier gain. Defaults to None.

        Returns:
            float: Number of the voltage in volts [V]. Returns value if no gain is given (no-connect).
        """
        if(ssGain != None and PreampGain == None) : 
            return(Packet_Binary5._Voltage_PrimaryChannels_Biosensor(value, ssGain))
        elif(ssGain != None):
            return(Packet_Binary5._Voltage_PrimaryChannels_EEGEMG(value, ssGain, PreampGain))
        else: 
            return(value) # no connect! this is noise 

    @staticmethod
    def _Voltage_PrimaryChannels_EEGEMG(value: int, ssGain: int, PreampGain: int) -> float : 
        """Converts a value to a voltage for an EEG/EMG primary channel. 

        Args:
            value (int): Value to be converted to voltage.
            ssGain (int): Second stage gain.
            PreampGain (int): Preamplifier gain.

        Returns:
            float: Number of the voltage in volts [V].
        """
        # Channels configured as EEG/EMG channels (0.4/1/10 Hz highpass filter, second stage 0.5Hz Highpass, second stage 5x)
        voltageAtADC = (value / 262144.0) * 4.096 # V
        totalGain    = 10.0 * ssGain * PreampGain # SSGain = 1 or 5, PreampGain = 10 or 100
        realVoltage  = (voltageAtADC - 2.048) / totalGain # V
        return(realVoltage)
    

    @staticmethod
    def _Voltage_PrimaryChannels_Biosensor(value: int, ssGain: int) -> float : 
        """Converts a value to a voltage for a biosensor primary channel. 

        Args:
            value (int): Value to be converted to voltage.
            ssGain (int): Second stage gain.

        Returns:
            float: Number of the voltage in volts [V]. 
        """
        # Channels configured as biosensor channels (DC highpass filter, second stage DC mode, second stage 1x)
        voltageAtADC = (value / 262144.0) * 4.096 # V
        totalGain    = 1.557 * ssGain * 1E7 # SSGain = 1 or 5
        realVoltage  = (voltageAtADC - 2.048) / totalGain # V
        return(realVoltage)

    @staticmethod
    def _Voltage_SecondaryChannels(value: int) -> float :
        """Converts a value to a voltage for a secondary channel.

        Args:
            value (int): Value to be converted to voltage.

        Returns:
            float: Number of the voltage in volts [V].
        """
        # The additional inputs (EXT0, EXT1, TTL1-3) values are all 12-bit referenced to 3.3V.  To convert them to real voltages, the formula is as follows
        return( (value / 4096.0) * 3.3 ) # V

# ==========================================================================================================

# class Packet_Binary2(Packet) : 
#     pass


# class Packet_Binary3(Packet) : 
#     pass


# class Packet_Binary5(Packet) : 
#     pass
