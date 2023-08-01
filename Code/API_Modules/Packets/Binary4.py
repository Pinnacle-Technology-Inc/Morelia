# enviornment imports
from typing import Any

# local imports
from Commands import POD_Commands
from Packets  import Packet

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

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

class Packet_Binary4(Packet) : 
    """Container class that stores a binary4 command packet for a POD device. The format is \
    STX (1 byte) + command (4 bytes) + packet number (1 byte) + TTL (1 byte) + \
    CH0 (2 bytes) + CH1 (2 bytes) + CH2 (2 bytes) + checksum (2 bytes) + ETX (1 byte). 

    Attributes:
        _preampGain (int): Preamplifier gain. This should be 10 or 100 for an 8206-HR device.
        packetNumber (bytes): Packet number for this POD packet.
        ttl (bytes): TTL data for this packet.
        ch0 (bytes): channel 0 data for this packet.
        ch1 (bytes): channel 1 data for this packet.
        ch2 (bytes): channel 2 data for this packet.
    """
    
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
            commands (POD_Commands | None, optional): Available commands for a POD device. \
                Defaults to None.
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
        return Packet.BinaryBytesToInt(self.packetNumber)
    
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
            int: Integer representing the minimum length of a binary4 POD packet. 
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
            msg (bytes): Bytes string containing a POD packet. Should begin with STX \
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
            'TTL1' : Packet.BinaryBytesToInt_Split(ttlByte, 8, 7), # TTL 0 
            'TTL2' : Packet.BinaryBytesToInt_Split(ttlByte, 7, 6), # TTL 1 
            'TTL3' : Packet.BinaryBytesToInt_Split(ttlByte, 6, 5), # TTL 2 
            'TTL4' : Packet.BinaryBytesToInt_Split(ttlByte, 5, 4)  # TTL 3 
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
        value_int = Packet.BinaryBytesToInt(value, byteorder='little')
        # calculate voltage 
        voltageADC = ( value_int / 65535.0 ) * 4.096 # V
        totalGain = preampGain * 50.2918
        realValue = ( voltageADC - 2.048 ) / totalGain
        # return the real value at input to preamplifier 
        return realValue # V 
