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

    # ============ DUNDER METHODS ============      ========================================================================================================================
    
    def __init__(self, port, preampGain, baudrate=9600) :
        # initialize POD_Basics
        super().__init__(port, baudrate=baudrate) 
        # get constants for adding commands 
        U8  = POD_Commands.U8()
        U16 = POD_Commands.U16()
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
        # self._commands.AddCommand( 181, 'BINARY5 DATA', 	    (0,),	    (???,),     False  )
    
    # ============ PUBLIC METHODS ============      ========================================================================================================================
    