# local imports
from PodPacketHandling import POD_Packets
from PodCommands import POD_Commands

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

# ==========================================================================================================

class Packet : 
    
    def __init__(self, pkt: bytes, commands: POD_Commands|None = None) -> None:
        """Sets the class instance variables. 

        Args:
            pkt (bytes): Bytes string containing a POD packet. Should begin with STX and ending with ETX.
            commands (POD_Commands | None, optional): _description_. Defaults to None.
        """
        self.rawPacket: bytes = bytes(pkt)
        self.commands: POD_Commands|None = commands
        
    @staticmethod
    def GetMinimumLength() -> int : 
        """Gets the number of bytes in the smallest possible packet. 

        Returns:
            int: integer representing the minimum length of a generic bytes string.
        """
        return(0)
    
    def HasCommands(self) -> bool:
        """Checks if the Packet instance has commands set.
        
        Returns:
            bool: True if the commands have been set, false otherwise.
        """ 
        return( isinstance(self.commands, POD_Commands) )


# ==========================================================================================================

class Packet_Standard(Packet) : 
    
    def __init__(self, pkt: bytes, commands: POD_Commands) -> None:
        super().__init__(pkt,commands)
        unpacked: dict[str,bytes] = Packet_Standard.UnpackPODpacket_Standard(self.rawPacket)
        self.commandNumber: bytes = unpacked['Command Number']
        if('Payload' in unpacked) : self.payload: bytes = unpacked['Payload']
        else :                      self.payload: None  = None
    
    
    @staticmethod
    def GetMinimumLength() -> int : 
        """Gets the number of bytes in the smallest possible packet. 
        
        Returns:
            int: integer representing the minimum length of a standard \
                POD command packet. Format is STX (1 byte) + command number (4 bytes) \
                + optional packet (? bytes) + checksum (2 bytes) + ETX (1 bytes)
        """
        return 8
    
    
    def HasPayload(self) -> bool : 
        """Checks if this Packet_Standard instance has a payload. 

        Returns:
            bool: True if there is a payload, false otherwise.
        """
        return( self.payload != None )
        
        
    def CommandNumber(self) -> int : 
        """Translate the binary ASCII encoding into a readable integer

        Returns:
            int: Integer of the command number.
        """
        # 
        return POD_Packets.AsciiBytesToInt(self.commandNumber)
        
        
    def Payload(self) -> tuple :
        """Splits the payload up into its components and translates the binary ASCII encoding \
        into a readable integer

        Returns:
            tuple[int]: Tuple with integer values for each component of the payload.
        """
        # check for payload 
        if(not self.HasPayload()) : return None
        # get format of payload 
        useSizes = (len(self.payload),)
        if(self.HasCommands()) : 
            cmd = self.CommandNumber()
            argSizes: tuple[int] = self.commands.ArgumentHexChar(cmd)
            retSizes: tuple[int] = self.commands.ReturnHexChar(cmd)
            # override which size tuple to use
            if(  sum(useSizes) == sum(argSizes)) : useSizes = argSizes
            elif(sum(useSizes) == sum(retSizes)): useSizes = retSizes
        # split up payload using tuple of sizes 
        pldSplit = [None]*len(useSizes)
        startByte = 0
        for i in range(len(useSizes)) : 
            endByte = startByte + useSizes[i] # count to stop byte
            pldSplit[i] = POD_Packets.AsciiBytesToInt(self.payload[startByte:endByte]) # get bytes 
            startByte = endByte # get new start byte
        return tuple(pldSplit) 
        
        
    @staticmethod
    def TranslatePODpacket_Standard(msg: bytes, commands: POD_Commands = None) -> dict[str,int] : 
        """Unpacks the standard POD packet and converts the ASCII-encoded bytes values into integer values. 

        Args: 
            msg (bytes): Bytes message containing a standard POD packet.

        Returns:
            dict[str,int]: A dictionary containing the POD packet's 'Command Number' and 'Payload' \
                (if applicable) in integers.
        """
        packetObj = Packet_Standard(msg,commands)
        msgDictTrans: dict[str,int] = { 'Command Number' : packetObj.CommandNumber() }
        if(packetObj.HasPayload()) : 
            msgDictTrans['Payload'] = packetObj.Payload()
        return msgDictTrans
        

    @staticmethod
    def UnpackPODpacket_Standard(msg: bytes) -> dict[str,bytes] : 
        """Converts a standard POD packet into a dictionary containing the command number and payload 
        (if applicable) in bytes.

        Args:
            msg (bytes): Bytes message containing a standard POD packet.

        Returns:
            dict[str,bytes]: A dictionary containing the POD packet's 'Command Number' and 'Payload' \
                (if applicable) in bytes.

        Raises: 
            Exception: (1) The msg does not have the minimum number of bytes in a standard pod packet, \
                (2) does not begin with STX, and (3) does not end with ETX. 
        """
        # standard POD packet with optional payload = STX (1 byte) + command number (4 bytes) + optional packet (? bytes) + checksum (2 bytes) + ETX (1 bytes)
        MINBYTES = Packet_Standard.GetMinimumLength()
        # get number of bytes in message
        packetBytes = len(msg)
        # message must have enough bytes, start with STX, or end with ETX
        if(    (packetBytes < MINBYTES)
            or (msg[0].to_bytes(1,'big') != POD_Packets.STX()) 
            or (msg[packetBytes-1].to_bytes(1,'big') != POD_Packets.ETX())
        ) : 
            raise Exception('Cannot unpack an invalid POD packet.')
        # create dict and add command number, payload, and checksum
        msg_unpacked = {'Command Number' : msg[1:5] }# 4 bytes after STX
        if( (packetBytes - MINBYTES) > 0) : # add packet to dict, if available 
            msg_unpacked['Payload'] = msg[5:(packetBytes-3)] # remaining bytes between command number and checksum 
        # return unpacked POD command
        return(msg_unpacked)

# ==========================================================================================================


# class Packet_BinaryStandard(Packet) : 
#     pass


# class Packet_Binary2(Packet) : 
#     pass


# class Packet_Binary3(Packet) : 
#     pass


# class Packet_Binary4(Packet) : 
#     pass


# class Packet_Binary5(Packet) : 
#     pass
