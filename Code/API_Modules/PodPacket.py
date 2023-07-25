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
    """Container class that stores a command packet for a POD device. The format is \
    STX (1 byte) + command number (4 bytes) + data (? bytes) + ETX (1 byte).
    
    Attributes:
        commands (POD_Commands | None): Available commands for a POD device. 
        rawPacket (bytes): Bytes string containing a POD packet. Should begin with STX and end with ETX.
        commandNumber (bytes | None): Command number from the Pod packet.
    """
    
    def __init__(self, pkt: bytes, commands: POD_Commands|None = None) -> None:
        """Sets the class instance variables. 

        Args:
            pkt (bytes): Bytes string containing a POD packet. Should begin with STX and end with ETX.
            commands (POD_Commands | None, optional): Available commands for a POD device. Defaults to None.
        """
        self.CheckIfPacketIsValid(pkt)
        self.commands:  POD_Commands|None = commands
        self.rawPacket: bytes = bytes(pkt)
        self.commandNumber: bytes|None = self.GetCommandNumber(pkt)
        
        
    def CommandNumber(self) -> int : 
        """Translate the binary ASCII encoding into a readable integer

        Returns:
            int: Integer of the command number.
        """
        return POD_Packets.AsciiBytesToInt(self.commandNumber)
        
        
    @staticmethod
    def GetCommandNumber(pkt: bytes) -> bytes|None :
        """Gets the command number bytes from a POD packet. 

        Args:
            pkt (bytes): Bytes string containing a POD packet. Should begin with STX and end with ETX.

        Returns:
            bytes|None: Bytes string of the command number, if available.
        """
        if(len(pkt) > Packet.GetMinimumLength() + 4) :
            return pkt[1:5]
        return None
    
    
    @staticmethod
    def GetMinimumLength() -> int : 
        """Gets the number of bytes in the smallest possible packet; STX (1 byte) + something + ETX (1 byte). 

        Returns:
            int: integer representing the minimum length of a generic bytes string.
        """
        return(2)
    
    
    @staticmethod
    def CheckIfPacketIsValid(msg: bytes) :
        """Raises an Exception if the packet is incorrectly formatted. 

        Args:
            msg (bytes):  Bytes string containing a POD packet. Should begin with STX and end with ETX.

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
        return( isinstance(self.commands, POD_Commands) )
    


# ==========================================================================================================


class Packet_Standard(Packet) : 
    """Container class that stores a standard command packet for a POD device. The format is \
    STX (1 byte) + command number (4 bytes) + optional packet (? bytes) + checksum (2 bytes) + ETX (1 bytes)
    
    Attributes:
        commands (POD_Commands | None, optional): Available commands for a POD device. 
        rawPacket (bytes): Bytes string containing a POD packet. Should begin with STX and end with ETX.
        commandNumber (bytes): Command number from the packet. 
        payload (bytes): Optional payload from the packet.
    """
    
    def __init__(self, pkt: bytes, commands: POD_Commands) -> None:
        """Sets the class instance variables. 

        Args:
            pkt (bytes): Bytes string containing a POD packet. Should begin with STX and ending with ETX.
            commands (POD_Commands | None, optional): _description_. Defaults to None.
        """
        super().__init__(pkt,commands)
        self.payload: bytes|None = self.GetPayload(pkt)
        
        
    def Payload(self) -> tuple :
        """Splits the payload up into its components and translates the binary ASCII encoding \
        into a readable integer.

        Returns:
            tuple[int]: Tuple with integer values for each component of the payload.
        """
        # check for payload 
        if(not self.HasPayload()) : return None
        # get format of payload 
        useSizes: tuple[int] = (len(self.payload),)
        if(self.HasCommands()) : 
            cmd = self.CommandNumber()
            argSizes: tuple[int] = self.commands.ArgumentHexChar(cmd)
            retSizes: tuple[int] = self.commands.ReturnHexChar(cmd)
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
    
    
    def HasPayload(self) -> bool : 
        """Checks if this Packet_Standard instance has a payload. 

        Returns:
            bool: True if there is a payload, false otherwise.
        """
        return( self.payload != None )
    
    
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
    
    
    @staticmethod
    def GetMinimumLength() -> int : 
        """Gets the number of bytes in the smallest possible packet. 
        
        Returns:
            int: integer representing the minimum length of a standard \
                POD command packet. Format is STX (1 byte) + command number (4 bytes) \
                + optional packet (? bytes) + checksum (2 bytes) + ETX (1 bytes)
        """
        return(8)
    
    @staticmethod   
    def CheckIfPacketIsValid(msg: bytes) :
        """Raises an Exception if the packet is incorrectly formatted. 

        Args:
            msg (bytes):  Bytes string containing a POD packet. Should begin with STX and end with ETX.

        Raises:
            Exception: Packet is too small to be a standard packet.
        """
        Packet.CheckIfPacketIsValid(msg)    
        if(len(msg) < Packet_Standard.GetMinimumLength()) : 
            raise Exception('Packet is too small to be a standard packet.')
    
    
    @staticmethod
    def TranslatePODpacket_Standard(msg: bytes, commands: POD_Commands = None) -> dict[str,int] : 
        """Unpacks the standard POD packet and converts the ASCII-encoded bytes values into integer values. 

        Args: 
            msg (bytes): Bytes message containing a standard POD packet.
            commands (POD_Commands, optional): Available commands for a POD device. Defaults to None.
            
        Returns:
            dict[str,int]: A dictionary containing the POD packet's 'Command Number' and 'Payload' \
                (if applicable) in integers.
        """
        packetObj = Packet_Standard(msg,commands)
        msgDictTrans: dict[str,int] = { 'Command Number' : packetObj.CommandNumber() }
        if(packetObj.HasPayload()) : msgDictTrans['Payload'] = packetObj.Payload()
        return msgDictTrans
        

    @staticmethod
    def UnpackPODpacket_Standard(msg: bytes) -> dict[str,bytes] : 
        """Converts a standard POD packet into a dictionary containing the command number and payload \
        (if applicable) in bytes.

        Args:
            msg (bytes): Bytes message containing a standard POD packet.

        Returns:
            dict[str,bytes]: A dictionary containing the POD packet's 'Command Number' and 'Payload' \
                (if applicable) in bytes.
        """
        # validate packet
        Packet_Standard.CheckIfPacketIsValid(msg)
        # add command number and payload to a dict
        msg_unpacked = {'Command Number' : Packet_Standard.GetCommandNumber(msg) } 
        pld = Packet_Standard.GetPayload(msg)
        if(pld != None) : msg_unpacked['Payload'] = pld
        # return finished dict
        return(msg_unpacked)
    

# ==========================================================================================================


class Packet_BinaryStandard(Packet) :     
    """Container class that stores a standard binary command packet for a POD device. The format is \
    STX (1 byte) + command number (4 bytes) + length of binary (4 bytes) + checksum (2 bytes) \
    + ETX (1 bytes) + binary (LENGTH bytes) + checksum (2 bytes) + ETX (1 bytes) 
    
    Attributes:
        rawPacket (bytes): Bytes string containing a POD packet. Should begin with STX and end with ETX.
        commands (POD_Commands | None, optional): Available commands for a POD device. 
        binaryLength (bytes): Number of bytes of binary data from the packet.
        binaryData (bytes): Variable length binary datafrom the packet.
    """

    def __init__(self, pkt: bytes, commands: POD_Commands | None = None) -> None:
        """Sets the class instance variables. 

        Args:
            pkt (bytes): Bytes string containing a POD packet. Should begin with STX and ending with ETX.
            commands (POD_Commands | None, optional): _description_. Defaults to None.
        """       
        super().__init__(pkt, commands)
        unpacked: dict[str,bytes] = Packet_BinaryStandard.UnpackPODpacket_Binary(self.rawPacket)
        self.binaryLength:  bytes = unpacked['Binary Packet Length']
        self.binaryData:    bytes = unpacked['Binary Data']
        
        
    def BinaryLength(self) -> int : 
        """Translate the binary ASCII encoding of the binary data length \
        into a readable integer

        Returns:
            int: Integer of the binary data length.
        """
        return POD_Packets.AsciiBytesToInt(self.binaryLength)

        
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
        
        
    @staticmethod
    def GetMinimumLength() -> int : 
        """Gets the number of bytes in the smallest possible packet; STX (1 byte) + something + ETX (1 byte). 

        Returns:
            int: integer representing the minimum length of a binary POD \
                command packet. Format is STX (1 byte) + command number (4 bytes) + length \
                of binary (4 bytes) + checksum (2 bytes) + ETX (1 bytes) + binary (LENGTH \
                bytes) + checksum (2 bytes) + ETX (1 bytes)
        """
        return(15)
    
    
    @staticmethod   
    def CheckIfPacketIsValid(msg: bytes) :
        """Raises an Exception if the packet is incorrectly formatted. 

        Args:
            msg (bytes):  Bytes string containing a POD packet. Should begin with STX and end with ETX.

        Raises:
            Exception: Packet is too small to be a standard packet.
            Exception: A standard binary packet must have an ETX before the binary bytes.
        """
        Packet.CheckIfPacketIsValid(msg) 
        if(len(msg) < Packet_BinaryStandard.GetMinimumLength()) : 
            raise Exception('Packet is too small to be a standard binary packet.')
        if(msg[11].to_bytes(1,'big') != POD_Packets.ETX()) : 
            raise Exception('A standard binary packet must have an ETX before the binary bytes.')


    @staticmethod
    def UnpackPODpacket_Binary(msg: bytes) -> dict[str,bytes]: 
        """Converts a variable-length binary packet into a dictionary containing the command 
        number, binary packet length, and binary data in bytes. 

        Args: 
            msg (bytes): Bytes message containing a variable-length POD packet

        Returns:
            dict[str,bytes]: A dictionary containing 'Command Number', 'Binary Packet Length', \
                and 'Binary Data' keys with bytes values.
        """
        Packet_BinaryStandard.CheckIfPacketIsValid(msg)
        # create dict and add command number and checksum
        return {
            'Command Number'        : Packet_BinaryStandard.GetCommandNumber(msg),
            'Binary Packet Length'  : Packet_BinaryStandard.GetBinaryLength(msg),
            'Binary Data'           : Packet_BinaryStandard.GetBinaryData(msg)
        }


    @staticmethod
    def TranslatePODpacket_Binary(msg: bytes, commands: POD_Commands = None) -> dict[str,int|bytes] : 
        """Unpacks the variable-length binary POD packet and converts the values of the ASCII-encoded \
        bytes into integer values and leaves the binary-encoded bytes as is. 

        Args:
            msg (bytes): Bytes message containing a variable-length POD packet.
            commands (POD_Commands, optional): Available commands for a POD device. Defaults to None.

        Returns:
            dict[str,int|bytes]: Dictionary containing the POD packet's 'Command Number', \
                'Binary Packet Length', and 'Binary Data'.
        """
        packetObj = Packet_BinaryStandard(msg,commands)
        # translate the binary ascii encoding into a readable integer
        return {
            'Command Number'        : packetObj.CommandNumber(),
            'Binary Packet Length'  : packetObj.BinaryLength(),
            'Binary Data'           : packetObj.binaryData # leave this as bytes, change type if needed 
        }
        
# ==========================================================================================================


# class Packet_Binary2(Packet) : 
#     pass


# class Packet_Binary3(Packet) : 
#     pass


# class Packet_Binary4(Packet) : 
#     pass


# class Packet_Binary5(Packet) : 
#     pass
