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
    
    def __init__(self, pkt: bytes, commands: POD_Commands|None = None) -> None:
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
    
    def __init__(self, pkt: bytes, commands: POD_Commands) -> None:
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

    def __init__(self, pkt: bytes, commands: POD_Commands | None = None) -> None:
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
    
    def __init__(self, pkt: bytes, preampGain: int, commands: POD_Commands | None = None) -> None:
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
        data['Packet #'] = self.packetNumber,
        data['TTL'] = self.ttl, 
        data['Ch0'] = self.ch0, 
        data['Ch1'] = self.ch1, 
        data['Ch2'] = self.ch2  
        return data

    def TranslateAll(self) -> dict[str, Any]:
        """Builds a dictionary containing all parts of the POD packet in readable values. 

        Returns:
            dict[str, Any]: Dictionary with the command number, packet number, TTL \
                and channels 0, 1, and 2.
        """
        data: dict = super().TranslateAll()
        data['Packet #'] = self.PacketNumber(),
        data['TTL'] = self.Ttl(), 
        data['Ch0'] = self.ch0, 
        data['Ch1'] = self.ch1, 
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
    
    def __init__(self, pkt: bytes, commands: POD_Commands | None = None) -> None:
        super().__init__(pkt, commands)
        pass
    
    # ----- Packet to dictionary -----
    
    def UnpackAll(self) -> dict[str, bytes]:
        pass
    
    def TranslateAll(self) -> dict[str, Any]:
        pass
    
    # ----- Translated parts -----
    
    def PacketNumber() -> int : 
        pass
    
    def Status() -> int : 
        pass

    def Channel(n: int) -> float : 
        pass
    
    def AnalogEXT(n: int) -> float : 
        pass
    
    def AnalogTTL(n: int) -> float : 
        pass
    
    # ----- Get parts from packet bytes -----
    
    @staticmethod
    def GetPacketNumber(pkt: bytes) -> bytes : 
        pass
    
    @staticmethod
    def GetStatus(pkt: bytes) -> bytes : 
        pass

    @staticmethod
    def GetChannels(pkt: bytes) -> bytes : 
        pass
    
    @staticmethod
    def GetAnalogEXT(n: int, pkt: bytes) -> bytes : 
        pass
    
    @staticmethod
    def GetAnalogTTL(n: int, pkt: bytes) -> bytes : 
        pass
        
    # ----- Properties -----
        
    @staticmethod
    def GetMinimumLength() -> int : 
        pass
    
    @staticmethod
    def GetBinaryLength() -> int :
        pass

    @staticmethod   
    def CheckIfPacketIsValid(msg: bytes) :
        pass
    
    # ----- Conversions -----



# ==========================================================================================================

# class Packet_Binary2(Packet) : 
#     pass


# class Packet_Binary3(Packet) : 
#     pass


# class Packet_Binary5(Packet) : 
#     pass
