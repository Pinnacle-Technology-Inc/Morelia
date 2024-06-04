# enviornment imports
from typing import Any
from collections.abc import Callable

# local imports
from Morelia.Commands import CommandSet
from Morelia.Packets  import Packet

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class  PacketStandard(Packet) : 
    """Container class that stores a standard command packet for a POD device. The format is \
    STX (1 byte) + command number (4 bytes) + optional payload (? bytes) + checksum (2 bytes) + ETX (1 bytes)
    
    Attributes:
        _customPayload (Callable[[Any],tuple]|None): Optional function to translate the payload. 
        _customPayloadArgs (tuple[Any]|None): Optional arguments for the _customPayload.
        payload (bytes): Optional payload from the packet.
    """
    
    def __init__(self, 
                 pkt: bytes, 
                 commands: CommandSet
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
        self._customPayloadArgs: tuple[Any]|None = None
    
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

    def SetCustomPayload(self, func: Callable[[Any],tuple], args: tuple[Any]|None = None) -> None :
        """Sets a custom function with optional arguments to translate the payload.

        Args:
            func (Callable[[Any],tuple]): Function to translate the payload.
            args (tuple[Any], optional): Arguments . Defaults to None.
        """
        self._customPayload: Callable[[Any],tuple] = func
        self._customPayloadArgs: tuple[Any]|None = args
        
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
        if(not self.HasPayload()):   
            return None
        if(self.HasCustomPayload()): 
            return self._customPayload(*self._customPayloadArgs)
        else:     
            return self.DefaultPayload()
        
    def DefaultPayload(self) -> tuple[int] :
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
            pldSplit[i] = Packet.AsciiBytesToInt(self.payload[startByte:endByte]) # get bytes 
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
        if( (len(pkt) - PacketStandard.GetMinimumLength()) > 0) :
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
        if(len(msg) < PacketStandard.GetMinimumLength()) : 
            raise Exception('Packet is too small to be a standard packet.')
        