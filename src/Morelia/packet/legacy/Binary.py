# enviornment imports
from typing import Any

# local imports
from Morelia.Commands import CommandSet
from Morelia.packet.legacy.Packet  import Packet

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class PacketBinary(Packet) :     
    """Container class that stores a standard binary command packet for a POD device. The format is \
    STX (1 byte) + command number (4 bytes) + length of binary (4 bytes) + checksum (2 bytes) \
    + ETX (1 bytes) + binary (LENGTH bytes) + checksum (2 bytes) + ETX (1 bytes) 
    
    Attributes:
        binaryLength (bytes): Number of bytes of binary data from the packet.
        binaryData (bytes): Variable length binary datafrom the packet.
    """

    def __init__(self, 
                 pkt: bytes, 
                 commands: CommandSet | None = None
                ) -> None:
        """Sets the class instance variables. 

        Args:
            pkt (bytes): Bytes string containing a POD packet. Should begin with STX and \
                ending with ETX.
            commands (POD_Commands | None, optional): Available commands for a POD device. \
                Defaults to None.
        """       
        super().__init__(pkt, commands)
        self.binaryLength:  bytes = PacketBinary.GetBinaryLength(pkt)
        self.binaryData:    bytes = PacketBinary.GetBinaryData(pkt)
               
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
        return Packet.AsciiBytesToInt(self.binaryLength)

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
    
    @staticmethod
    def GetBinaryData(pkt: bytes) -> bytes : 
        """Gets the binary data from a POD packet.

        Args:
            pkt (bytes): Bytes string containing a POD packet.

        Returns:
            bytes: Bytes string containg binary data.
        """
        return pkt[12:(len(pkt)-3)] # bytes after 1st ETX

    @staticmethod
    def GetMinimumLength() -> int : 
        """Gets the number of bytes in the smallest possible packet.

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
        if(len(msg) < PacketBinary.GetMinimumLength()) : 
            raise Exception('Packet is too small to be a standard binary packet.')
        if(msg[11].to_bytes(1,'big') != Packet.ETX()) : 
            raise Exception('A standard binary packet must have an ETX before the binary bytes.')
        
