# enviornment imports
from typing import Any

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