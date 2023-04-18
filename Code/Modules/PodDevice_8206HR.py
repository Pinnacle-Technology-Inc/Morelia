"""
POD_8206HR handles communication using an 8206HR POD device. 
"""

# local imports 
from BasicPodProtocol       import POD_Basics
from PodPacketHandling      import POD_Packets
from PodCommands            import POD_Commands

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class POD_8206HR(POD_Basics) : 

    # ============ GLOBAL CONSTANTS ============    ========================================================================================================================


    # number of bytes for a Binary 4 packet 
    __B4LENGTH       = 16
    # number of binary bytes for a Binary 4 packet 
    __B4BINARYLENGTH = __B4LENGTH - 8 # length minus STX(1), command number(4), checksum(2), ETX(1) || 16 - 8 = 8


    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self, port, preampGain, baudrate=9600) :
        # initialize POD_Basics
        super().__init__(port, baudrate=baudrate) 
        # get constants for adding commands 
        U8  = POD_Commands.U8()
        U16 = POD_Commands.U16()
        B4  = POD_8206HR.__B4BINARYLENGTH
        # remove unimplemented commands 
        self._commands.RemoveCommand(5)  # STATUS
        self._commands.RemoveCommand(9)  # ID
        self._commands.RemoveCommand(10) # SAMPLE RATE
        self._commands.RemoveCommand(11) # BINARY
        # add device specific commands
        self._commands.AddCommand(100, 'GET SAMPLE RATE',      (0,),       (U16,),    False   )
        self._commands.AddCommand(101, 'SET SAMPLE RATE',      (U16,),     (0,),      False   )
        self._commands.AddCommand(102, 'GET LOWPASS',          (U8,),      (U16,),    False   )
        self._commands.AddCommand(103, 'SET LOWPASS',          (U8,U16),   (0,),      False   )
        self._commands.AddCommand(104, 'SET TTL OUT',          (U8,U8),    (0,),      False   )
        self._commands.AddCommand(105, 'GET TTL IN',           (U8,),      (U8,),     False   )
        self._commands.AddCommand(106, 'GET TTL PORT',         (0,),       (U8,),     False   )
        self._commands.AddCommand(107, 'GET FILTER CONFIG',    (0,),       (U8,),     False   )
        self._commands.AddCommand(180, 'BINARY4 DATA ',        (0,),       (B4,),     True    )     # see _Read_Binary()
        # preamplifier gain (should be 10x or 100x)
        if(preampGain != 10 and preampGain != 100):
            raise Exception('[!] Preamplifier gain must be 10 or 100.')
        self._preampGain = preampGain 


    # ============ PUBLIC METHODS ============      ========================================================================================================================
    

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
            or (msg[0].to_bytes(1,'big') != POD_Packets.STX()) 
            or (msg[packetBytes-1].to_bytes(1,'big') != POD_Packets.ETX())
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


    def TranslatePODpacket_Binary(self, msg): 
        # unpack parts of POD packet into dict
        msgDict = POD_8206HR.UnpackPODpacket_Binary(msg)
        # initialize dictionary for translated values 
        msgDictTrans = {}
        # translate the binary ascii encoding into a readable integer
        msgDictTrans['Command Number']  = POD_Packets.AsciiBytesToInt(msgDict['Command Number'])
        msgDictTrans['Packet #']        = POD_Packets.BinaryBytesToInt(msgDict['Packet #'])
        msgDictTrans['TTL']             = POD_Packets.BinaryBytesToInt(msgDict['TTL'])
        msgDictTrans['Ch0']             = self.BinaryBytesToVoltage(msgDict['Ch0'])
        msgDictTrans['Ch1']             = self.BinaryBytesToVoltage(msgDict['Ch1'])
        msgDictTrans['Ch2']             = self.BinaryBytesToVoltage(msgDict['Ch2'])
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


    def TranslatePODpacket(self, msg):
        # message is binary 
        if(len(msg) == POD_8206HR.__B4LENGTH) : 
            return( self.TranslatePODpacket_Binary(msg) ) 
        # message may be standard (length checked within unpacking function )
        else :
            return( self.TranslatePODpacket_Standard(msg) )


    # ------------ CONVERSIONS ------------           ------------------------------------------------------------------------------------------------------------------------
    

    def BinaryBytesToVoltage(self, value):
        # convert binary message from POD to integer
        value_int = POD_Packets.BinaryBytesToInt(value, byteorder='little')
        # calculate voltage 
        voltageADC = ( value_int / 65535 ) * 4.096 #V
        totalGain = self._preampGain * 50.2918
        realValue = ( voltageADC - 2.048 ) / totalGain
        # return the real value at input to preamplifier 
        return(realValue) #V 


    # ============ PROTECTED METHODS ============      ========================================================================================================================


    # ------------ OVERWRITE ------------           ------------------------------------------------------------------------------------------------------------------------


    def _Read_Binary(self, prePacket, validateChecksum=True):
        """
        Binary 4 Data Format
        ------------------------------------------------------------		
        Byte    Value	        Format      Description 
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
        # get prepacket + packet number, TTL, and binary ch0-2 (these are all binary, do not search for STX/ETX) + read csm and ETX (3 bytes) (these are ASCII, so check for STX/ETX)
        packet = prePacket + self._port.Read(self.__B4BINARYLENGTH) + self._Read_ToETX(validateChecksum=validateChecksum)
        # check if checksum is correct 
        if(validateChecksum):
            if(not self._ValidateChecksum(packet) ) :
                raise Exception('Bad checksum for binary POD packet read.')
        # return complete variable length binary packet
        return(packet)