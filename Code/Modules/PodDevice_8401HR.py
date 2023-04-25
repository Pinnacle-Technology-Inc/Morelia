"""
POD_8401HR handles communication using an 8401-HR POD device. 
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

class POD_8401HR(POD_Basics) : 

    # ============ GLOBAL CONSTANTS ============    ========================================================================================================================

    # number of bytes for a Binary 5 packet 
    __B5LENGTH = 31
    # number of binary bytes for a Binary 5 packet 
    __B5BINARYLENGTH = __B5LENGTH - 8 # length minus STX(1), command number(4), checksum(2), ETX(1) || 31 - 8 = 23

    # ============ DUNDER METHODS ============      ========================================================================================================================
    
    def __init__(self, port, baudrate=9600) :
        # initialize POD_Basics
        super().__init__(port, baudrate=baudrate) 
        # get constants for adding commands 
        U8  = POD_Commands.U8()
        U16 = POD_Commands.U16()
        B5  = POD_8401HR.__B5BINARYLENGTH
        # remove unimplemented commands 
        self._commands.RemoveCommand(5)  # STATUS
        self._commands.RemoveCommand(10) # SAMPLE RATE
        self._commands.RemoveCommand(11) # BINARY
        # add device specific commands
        self._commands.AddCommand( 100, 'GET SAMPLE RATE',      (0,),       (U16,),     False  )
        self._commands.AddCommand( 101, 'SET SAMPLE RATE',      (U16,),     (0,),       False  )
        self._commands.AddCommand( 102,	'GET HIGHPASS',	        (U8,),	    (U8,),      False  )
        self._commands.AddCommand( 103,	'SET HIGHPASS',	        (U8, U8),	(0,),       False  )
        self._commands.AddCommand( 104,	'GET LOWPASS',	        (U8,),	    (U16,),     False  )
        self._commands.AddCommand( 105,	'SET LOWPASS',	        (U8, U16),	(0,),       False  )
        self._commands.AddCommand( 106,	'GET DC MODE',	        (U8,),	    (U8,),      False  )
        self._commands.AddCommand( 107,	'SET DC MODE',	        (U8, U8),	(0,),       False  )
        self._commands.AddCommand( 112,	'GET BIAS',	            (U8,),	    (U16,),     False  )
        self._commands.AddCommand( 113,	'SET BIAS',	            (U8, U16),	(0,),       False  )
        self._commands.AddCommand( 114,	'GET EXT0 VALUE',	    (0,),	    (U16,),     False  )
        self._commands.AddCommand( 115,	'GET EXT1 VALUE',	    (0,),	    (U16,),     False  )
        self._commands.AddCommand( 116,	'SET EXT0',	            (U8,),	    (0,),       False  )
        self._commands.AddCommand( 117,	'SET EXT1',	            (U8,),	    (0,),       False  )
        self._commands.AddCommand( 118,	'MEASURE OFFSETS',	    (0,),	    (0,),       False  )
        self._commands.AddCommand( 119,	'GET OFFSETS',	        (0,),	    (0,),       False  )
        self._commands.AddCommand( 120,	'GET OFFSETS',	        (U8, U8),	(U16,),     False  )
        self._commands.AddCommand( 121,	'SET INPUT GROUND',	    (U8,),	    (0,),       False  )
        self._commands.AddCommand( 122,	'GET INPUT GROUND',	    (0,),	    (U8,),      False  )
        self._commands.AddCommand( 127,	'SET TTL CONFIG',	    (U8, U8),	(0,),       False  )
        self._commands.AddCommand( 128,	'GET TTL CONFIG',	    (0,),	    (U8, U8),   False  )
        self._commands.AddCommand( 129,	'SET TTL OUTS',	        (U8, U8),	(0,),       False  )
        self._commands.AddCommand( 130,	'GET SS CONFIG',	    (U8,),	    (U8,),      False  )
        self._commands.AddCommand( 131,	'SET SS CONFIG',	    (U8, U8),	(0,),       False  )
        self._commands.AddCommand( 132,	'SET MUX MODE',	        (U8,),	    (0,),       False  )
        self._commands.AddCommand( 133,	'GET MUX MODE',	        (0,),	    (U8,),      False  )
        self._commands.AddCommand( 134,	'GET TTL ANALOG',	    (U8,),	    (U16,),     False  )
        self._commands.AddCommand( 181, 'BINARY5 DATA', 	    (0,),	    (B5,),      True   )
    
    # ============ PUBLIC METHODS ============      ========================================================================================================================
    
    
    # ------------ OVERWRITE ------------           ------------------------------------------------------------------------------------------------------------------------
    
    
    @staticmethod
    def UnpackPODpacket_Binary(msg) :
        pass


    def TranslatePODpacket_Binary(self, msg): 
        pass

    # ------------ SIMPLE ------------           ------------------------------------------------------------------------------------------------------------------------


    @staticmethod
    def UnpackPODpacket(msg):
        # determine what type of pod packet using length of msg
        length = len(msg)
        # message is binary 
        if(length == POD_8401HR.__B5LENGTH) : 
            return( POD_8401HR.UnpackPODpacket_Binary(msg) ) 
        # message may be standard (length checked within unpacking function )
        else :
            return( POD_8401HR.UnpackPODpacket_Standard(msg) ) 


    def TranslatePODpacket(self, msg):
        # message is binary 
        if(len(msg) == POD_8401HR.__B5LENGTH) : 
            return( self.TranslatePODpacket_Binary(msg) ) 
        # message may be standard (length checked within unpacking function )
        else :
            return( self.TranslatePODpacket_Standard(msg) )


    # ============ PROTECTED METHODS ============      ========================================================================================================================


    # ------------ OVERWRITE ------------           ------------------------------------------------------------------------------------------------------------------------

    def _Read_Binary(self, prePacket, validateChecksum=True):
        """
        Binary 4 Data Format
        -----------------------------------------------------------------------------		
        Byte    Value	                        Format      Description 
        -----------------------------------------------------------------------------		
        0	    0x02	                        Binary		STX
        1	    0	                            ASCII		Command Number Byte 0
        2	    0	                            ASCII		Command Number Byte 1
        3	    B	                            ASCII		Command Number Byte 2
        4	    5	                            ASCII		Command Number Byte 3
        5	    Packet Number 	                Binary		A rolling value that increases with each packet, and rolls over to 0 after it hits 255
        6	    Status	                        Binary		Status byte, currently unused
        7	    CH3 17~10	                    Binary		Top 8 bits of CH3.  Data is 18 bits, packed over 3 bytes.  Because of this the number of bits in each byte belonging to each chanenl changes.  Values are sent MSB/MSb first
        8	    CH3 9~2	                        Binary		Middle 8 bits of CH3
        9	    CH3 1~0, CH2 17~12	            Binary		Bottom 2 bits of CH3 and top 6 bits of CH2
        10	    CH2 11~4	                    Binary		Middle 8 bits of Ch2
        11	    CH2 3~0, CH1 17~14	            Binary		Bottom 4 bits of CH2 and top 4 bits of CH1
        12	    CH1 13~6	                    Binary		Middle 8 bits of CH1
        13	    CH1 5~0, CH0 17~16	            Binary		Bottom 6 bits of CH1 and top 2 bits of CH0
        14	    CH0 15~8	                    Binary		Middle 8 bits of Ch0
        15	    CH0 7~0	                        Binary		Bottom 8 bits of CH0
        16	    EXT0 Analog Value High Byte	    Binary		Top nibble of the 12-bit EXT0 analog value.  Sent MSB/MSb first
        17	    EXT0 Analog Value Low Byte	    Binary		Bottom nibble of the EXT0 value
        18	    EXT1 Analog Value High Byte	    Binary		Top nibble of the 12-bit EXT1 analog value.  Sent MSB/MSb first
        19	    EXT1 Analog Value Low Byte	    Binary		Bottom nibble of the EXT1 value
        20	    TTL1 Analog Value High Byte	    Binary		Top nibble of the TTL1 pin read as a 12-bit analog value
        21	    TTL1 Analog Value Low Byte	    Binary		Bottom nibble of the TTL2 pin analog value
        22	    TTL2 Analog Value High Byte	    Binary		Top nibble of the TTL1 pin read as a 12-bit analog value
        23	    TTL2 Analog Value Low Byte	    Binary		Bottom nibble of the TTL2 pin analog value
        24	    TTL3 Analog Value High Byte	    Binary		Top nibble of the TTL3 pin read as a 12-bit analog value
        25	    TTL3 Analog Value Low Byte	    Binary		Bottom nibble of the TTL3 pin analog value
        26	    TTL4 Analog Value High Byte	    Binary		Top nibble of the TTL4 pin read as a 12-bit analog value
        27	    TTL4 Analog Value Low Byte	    Binary		Bottom nibble of the TTL4 pin analog value
        28	    Checksum MSB	                ASCII		Checksum
        29	    Checksum LSB	                ASCII		Checksum 
        30	    0x03	                        Binary		ETX
        -----------------------------------------------------------------------------
        """
        # get prepacket (STX+command number) (5 bytes) + 23 binary bytes (do not search for STX/ETX) + read csm and ETX (3 bytes) (these are ASCII, so check for STX/ETX)
        packet = prePacket + self._port.Read(self.__B5BINARYLENGTH) + self._Read_ToETX(validateChecksum=validateChecksum)
        # check if checksum is correct 
        if(validateChecksum):
            if(not self._ValidateChecksum(packet) ) :
                raise Exception('Bad checksum for binary POD packet read.')
        # return complete variable length binary packet
        return(packet)