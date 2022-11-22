from BasicPodProtocol import POD_Basics
from PodCommands import POD_Commands

class POD_8206HR(POD_Basics) : 

    # ============ GLOBAL CONSTANTS ============    ========================================================================================================================

    # number of bytes for ch0-2 in a  Binary 4 packet 
    __B4CHLENGTH = 6
    # number of bytes for a Binary 4 packet 
    __B4LENGTH = __B4CHLENGTH + 10 

    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self, port, baudrate=9600) :
        # initialize POD_Basics
        super().__init__(port, baudrate=baudrate) 
        # get constants for adding commands 
        U8  = POD_Commands.U8()
        U16 = POD_Commands.U16()
        B4 = POD_8206HR.__B4CHLENGTH
        # remove unimplemented commands 
        self._commands.RemoveCommand(5)  # STATUS
        self._commands.RemoveCommand(9)  # ID
        self._commands.RemoveCommand(10) # SAMPLE RATE
        self._commands.RemoveCommand(11) # BINARY
        # add device specific commands
        self._commands.AddCommand(100, 'GET SAMPLE RATE',      0,       U16,    False   )
        self._commands.AddCommand(101, 'SET SAMPLE RATE',      U16,     0,      False   )
        self._commands.AddCommand(102, 'GET LOWPASS',          U8,      U16,    False   )
        self._commands.AddCommand(103, 'SET LOWPASS',          U8+U16,  0,      False   )
        self._commands.AddCommand(104, 'SET TTL OUT',          U8+U8,   0,      False   )
        self._commands.AddCommand(105, 'GET TTL IN',           U8,      U8,     False   )
        self._commands.AddCommand(106, 'GET TTL PORT',         0,       U8,     False   )
        self._commands.AddCommand(107, 'GET FILTER CONFIG',    0,       U8,     False   )
        self._commands.AddCommand(180, 'BINARY4 DATA ',        0,       B4,     True    )     # see ReadPODpacket_Binary()


    # ============ STATIC METHODS ============      ========================================================================================================================


    # ------------ OVERWRITE ------------           ------------------------------------------------------------------------------------------------------------------------


    @staticmethod
    def UnpackPODpacket_Binary(msg) :
        # Binary 4 format = 
        #   STX (1 byte) + command (4 bytes) + packet number (1 bytes) + TTL (1 byte) 
        #   + ch0 (2 bytes) + ch1 (2 bytes) + ch2 (2 bytes) + checksum (2 bytes) + ETX (1 byte)
        MINBYTES = POD_8206HR.__B4LENGTH

        # get number of bytes in message
        packetBytes = len(msg)

        # message must have enough bytes, start with STX, or end with ETX
        if(    (packetBytes != MINBYTES)
            or (msg[0].to_bytes(1,'big') != POD_Basics.STX()) 
            or (msg[packetBytes-1].to_bytes(1,'big') != POD_Basics.ETX())
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


    @staticmethod
    def TranslatePODpacket_Binary(msg): 
        # unpack parts of POD packet into dict
        msgDict = POD_8206HR.UnpackPODpacket_Binary(msg)
        # initialize dictionary for translated values 
        msgDictTrans = {}
        # translate the binary ascii encoding into a readable integer
        msgDictTrans['Command Number']  = POD_Basics.AsciiBytesToInt(msgDict['Command Number'])
        msgDictTrans['Packet #']        = POD_Basics.BinaryBytesToInt(msgDict['Packet #'])
        msgDictTrans['TTL']             = POD_Basics.BinaryBytesToInt(msgDict['TTL'])
        msgDictTrans['Ch0']             = POD_Basics.BinaryBytesToInt(msgDict['Ch0']) # do I want these as int or keep as binary ?
        msgDictTrans['Ch1']             = POD_Basics.BinaryBytesToInt(msgDict['Ch1']) # do I want these as int or keep as binary ?
        msgDictTrans['Ch2']             = POD_Basics.BinaryBytesToInt(msgDict['Ch2']) # do I want these as int or keep as binary ?
        # return translated unpacked POD packet 
        return(msgDictTrans)


    # ------------ SIMPLE ------------           ------------------------------------------------------------------------------------------------------------------------


    @staticmethod
    def UnpackPODpacket(msg):
        # determine what type of pod packet using length of msg
        length = len(msg)
        # message is binary 
        if(length == POD_8206HR.__B4LENGTH) : 
            return( POD_8206HR.UnpackPODpacket_Binary(msg) ) 
        # message may be standard (length checked within unpacking function )
        else :
            return( POD_8206HR.UnpackPODpacket_Standard(msg) ) 


    @staticmethod
    def TranslatePODpacket(msg):
        # determine what type of pod packet using length of msg
        length = len(msg)
        # message is binary 
        if(length == POD_8206HR.__B4LENGTH) : 
            return( POD_8206HR.TranslatePODpacket_Binary(msg) ) 
        # message may be standard (length checked within unpacking function )
        else :
            return( POD_8206HR.TranslatePODpacket_Standard(msg) )


    # ============ PROTECTED METHODS ============      ========================================================================================================================


    # ------------ OVERWRITE ------------           ------------------------------------------------------------------------------------------------------------------------


    def _Read_Binary(self, prePacket, validateChecksum=True):
        """
        Binary 4 Data Format
        ------------------------------------------------------------		
        Byte    Index	        Value	
        ------------------------------------------------------------		
        0	    0x02	        Binary		STX
        1	    0	            ASCII		Command Number Byte 0
        2	    0	            ASCII		Command Number Byte 1
        3	    B	            ASCII		Command Number Byte 2
        4	    4	            ASCII		Command Number Byte 3
        5	    Packet Number 	Binary		A rolling value that increases with each packet, and rolls over to 0 after it hits 255
        6	    TTL	            Binary		The byte value of the TTL port.  Value would be equivalent to the command 106 GET TTL PORT above
        7	    Ch0 LSB	        Binary		Least significant byte of the Channel 0 (EEG1) value
        8	    Ch0 MSB	        Binary		Most significant byte of the Channel 0 (EEG1) value
        9	    Ch1 LSB	        Binary		Channel 1 / EEG2 LSB
        10	    Ch1 MSB	        Binary		Channel 1 / EEG2 MSB
        11	    Ch2 LSB	        Binary		Channel 2 / EEG3/EMG LSB
        12	    Ch2 MSB	        Binary		Channel 2 / EEG3/EMG MSB
        13	    Checksum MSB	ASCII		MSB of checksum
        14	    Checksum LSB	ASCII		LSB of checkxum
        15	    0x03	        Binary		ETX
        ------------------------------------------------------------
        """
        # initialize packet 
        packet = prePacket # STX + command 

        # read packet number and TTL (2 bytes)
        b = None 
        countToBinary = 0
        while(countToBinary < 2) :
            # read next byte and add to packet 
            countToBinary += 1
            b = self._port.Read(1)
            packet += b
            # start over if STX is found 
            if(b == self.STX() ) : 
                self._ReadPODpacket_Recursive(validateChecksum=validateChecksum)
            # return if ETX is found
            if(b == self.ETX() ) : 
                return(packet)

        # read binary packet (6 bytes)
        packet += self._port.Read(POD_8206HR.__B4CHLENGTH)

        # read csm and ETX (3 bytes)
        packet += self._Read_ToETX(validateChecksum=validateChecksum)

        # check if checksum is correct 
        if(validateChecksum):
            if(not self._ValidateChecksum(packet) ) :
                raise Exception('Bad checksum for binary POD packet read.')

        # return complete variable length binary packet
        return(packet)


    # def ReadPODpacket_Binary(self, validateChecksum=True) :
    #     """
    #     Binary 4 Data Format
    #     ------------------------------------------------------------		
    #     Byte    Index	        Value	
    #     ------------------------------------------------------------		
    #     0	    0x02	        Binary		STX
    #     1	    0	            ASCII		Command Number Byte 0
    #     2	    0	            ASCII		Command Number Byte 1
    #     3	    B	            ASCII		Command Number Byte 2
    #     4	    4	            ASCII		Command Number Byte 3
    #     5	    Packet Number 	Binary		A rolling value that increases with each packet, and rolls over to 0 after it hits 255
    #     6	    TTL	            Binary		The byte value of the TTL port.  Value would be equivalent to the command 106 GET TTL PORT above
    #     7	    Ch0 LSB	        Binary		Least significant byte of the Channel 0 (EEG1) value
    #     8	    Ch0 MSB	        Binary		Most significant byte of the Channel 0 (EEG1) value
    #     9	    Ch1 LSB	        Binary		Channel 1 / EEG2 LSB
    #     10	    Ch1 MSB	        Binary		Channel 1 / EEG2 MSB
    #     11	    Ch2 LSB	        Binary		Channel 2 / EEG3/EMG LSB
    #     12	    Ch2 MSB	        Binary		Channel 2 / EEG3/EMG MSB
    #     13	    Checksum MSB	ASCII		MSB of checksum
    #     14	    Checksum LSB	ASCII		LSB of checkxum
    #     15	    0x03	        Binary		ETX
    #     ------------------------------------------------------------
    #     """
    #     # read until STX found
    #     packet = None
    #     while(packet != self.STX()) :
    #         packet = self._port.Read(1)     # read next byte  

    #     # read remaining bytes
    #     packet += self._port.Read(POD_8206HR.__B4LENGTH-1) # == 16 - 1

    #     # verify that Last is ETX
    #     last = packet[len(packet)-1].to_bytes(1,'big')
    #     if(last != self.ETX()) : 
    #         raise Exception('Bad binary read.')
        
    #     if(validateChecksum) :
    #         # raise exception if chacksum is invalid
    #         if(POD_Basics.ValidateChecksum(packet) == False ):
    #             raise Exception('Bit error in recieved POD message.')

    #     # return full binary packet
    #     return(packet)