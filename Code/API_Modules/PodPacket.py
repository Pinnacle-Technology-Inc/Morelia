# local imports
from PodPacketHandling import POD_Packets

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"


class Packet : 
    
    def __init__(self, pkt: bytes) -> None:
        """Set class instance variables. 

        Args:
            pkt (bytes): Bytes string containing a POD packet. Should begin with STX and ending with ETX.
        """
        self.rawPacket : bytes = pkt
        
    @staticmethod
    def GetMinimumLength() -> int : 
        """Gets the number of bytes in the smallest possible packet. 

        Returns:
            int: integer representing the minimum length of a generic bytes string.
        """
        return(0)


class Packet_Standard(Packet) : 
    
    def __init__(self, pkt: bytes) -> None:
        super().__init__(pkt)
        unpacked = Packet_Standard.UnpackPODpacket_Standard(self.rawPacket)
        self.commandNumber = unpacked['Command Number']
        self.payload = unpacked['Payload']
        
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
        # standard POD packet with optional payload = 
        #   STX (1 byte) + command number (4 bytes) + optional packet (? bytes) + checksum (2 bytes) + ETX (1 bytes)
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
        msg_unpacked = {}
        msg_unpacked['Command Number']  = msg[1:5]                                  # 4 bytes after STX
        if( (packetBytes - MINBYTES) > 0) : # add packet to dict, if available 
            msg_unpacked['Payload']     = msg[5:(packetBytes-3)]                    # remaining bytes between command number and checksum 

        # return unpacked POD command
        return(msg_unpacked)


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
