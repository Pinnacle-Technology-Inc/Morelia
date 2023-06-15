"""
POD_8480HR handles communication using an 8480-HR POD device. 
"""

# local imports 
from BasicPodProtocol       import POD_Basics
from PodPacketHandling      import POD_Packets
from PodCommands            import POD_Commands

# authorship
__author__      = "Sree Kondi"
__maintainer__  = "Sree Kondi"
__credits__     = ["Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Sree Kondi"
__email__       = "sales@pinnaclet.com"

class POD_8480HR(POD_Basics) : 

    # ============ GLOBAL CONSTANTS ============    ========================================================================================================================


    # # number of bytes for a Binary 5 packet 
    # __B5LENGTH : int = 31
    # # number of binary bytes for a Binary 5 packet 
    # __B5BINARYLENGTH : int = __B5LENGTH - 8 # length minus STX(1), command number(4), checksum(2), ETX(1) || 31 - 8 = 23


    # ============ DUNDER METHODS ============      ========================================================================================================================
    

    def __init__(self, port: str|int, baudrate:int=9600) -> None :

        super().__init__(port, baudrate=baudrate) #inheritance 
        U8  = POD_Commands.U8()
        U16 = POD_Commands.U16()
        U32 = POD_Commands.U32()

        self._commands.RemoveCommand(10) # SAMPLE RATE
        
        # add device specific commands
        self._commands.AddCommand(  10, 'STRATE',               (0,),                               (0,),                                False  ) # Requires U8 Channel.  Runs the stimulus on the selected channel (0 or 1).  Will generally be immediately followed by a 133 EVENT STIM START packet, and followed by a 134 EVENT STIM END packet after the stimulus completes
        self._commands.AddCommand( 100, 'RUN STIMULUS',         (U8,),                              (0,),                                False  ) # Requires U8 Channel.  Runs the stimulus on the selected channel (0 or 1).  Will generally be immediately followed by a 133 EVENT STIM START packet, and followed by a 134 EVENT STIM END packet after the stimulus completes
        self._commands.AddCommand( 101, 'GET STIMULUS',         (U8,),                              (U8, U16, U16, U16, U16, U32, U8),   False  ) # Requires U8 Channel.  Gets the current stimulus configuration for the selected channel.  See format below. 
        self._commands.AddCommand( 102,	'SET STIMULUS',	        (U8, U16, U16, U16, U16, U32, U8),	(0,),                                False  ) # Sets the stimulus configuration on the selected channel.  See format below. 
        self._commands.AddCommand( 108,	'GET TTL SETUP',	    (U8,),	                            (U8, U8),                            False  ) # Requires U8 channel.  Returns U8 config flags, and U8 debounce value in ms.  See below for config flags format
        self._commands.AddCommand( 109,	'SET TTL SETUP',	    (U8,),	                            (U8, U8),                            False  ) # Sets the TTL setup for the channel.  Format is Channel, Config Flags, Debounce in ms.  See below for config flags format
        self._commands.AddCommand( 110,	'GET TTL PULLUPS',	    (0,),	                            (U8,),                               False  ) # Gets whether TTL pullups are enabled on the TTL lines.  0 = no pullups, non-zero = pullups enabled
        self._commands.AddCommand( 111,	'SET TTL PULLUPS',	    (U8,),	                            (0,),                                False  ) # Sets whether pullups are enabled on the TTL lines.  0 = pullups disabled, non-zero = pullups enabled
        self._commands.AddCommand( 116,	'GET LED CURRENT',	    (0,),	                            (U16, U16),                          False  ) # Gets the setting for LED current for both channels in mA.  CH0 CH1
        self._commands.AddCommand( 117, 'SET LED CURRENT',	    (U8, U16),	                        (0,),                                False  ) # Requires U8 channel.  Sets the selected channel LED current to the given value in mA, from 0-600
        self._commands.AddCommand( 118,	'GET ESTIM CURRENT',	(0,),	                            (U16, U16),                          False  ) # Gets the setting for the ESTIM current for both channels, in percentage.  CH0 then CH1
        self._commands.AddCommand( 119,	'SET ESTIM CURRENT',	(U8, U16),	                        (0,),                                False  ) # Requires U8 channel.  Sets the selected chanenl ESTIM current to the given value in percentage, from 0-100
        self._commands.AddCommand( 124,	'GET PREAMP TYPE',	    (0,),	                            (U16,),                              False  ) # gets the store preamp value
        self._commands.AddCommand( 125,	'SET PREAMP TYPE',	    (U16,),	                            (0,),                                False  ) # Sets the preamp value, from 0-1023.  This should match the table in Sirenia, it's a 10-bit code that tells the 8401 what preamp is connected.  Only needed when used with an 8401. See table below.
        self._commands.AddCommand( 126,	'GET SYNC CONFIG',	    (0,),	                            (U8,),                               False  ) # Gets the sync config byte.  See format below
        self._commands.AddCommand( 127,	'SET SYNC CONFIG',	    (U8,),	                            (0,),                                False  ) # Sets the sync config byte.  See format below
        self._commands.AddCommand( 132,	'EVENT TTL',	        (0,),	                            (U8,),                               False  ) # Indicates a TTL event has occurred on the indicated U8 TTL input.  If debounce is non-zero then this will not occur until the debounce has completed successfully.
        self._commands.AddCommand( 133,	'EVENT STIM START',	    (0,),	                            (U8,),                               False  ) # Indicates the start of a stimulus.  Returns U8 channel
        self._commands.AddCommand( 134,	'EVENT STIM STOP',	    (0,),	                            (U8,),                               False  ) # Indicates the end of a stimulus. Returns U8 channel
        self._commands.AddCommand( 135,	'EVENT LOW CURRENT',	(0,),	                            (U8,),                               False  ) # Indicates a low current status on one or more of the LED channels.  U8 bitmask indication which channesl have low current.  Bit 0 = Ch0, Bit 1 = Ch1

    @staticmethod
    def StimulusConfigBits(optoElec:bool, monoBiphasic:bool, Simul:bool) -> int :
        return (0 | (optoElec << 2) | (monoBiphasic << 1) | (Simul))
        
    # TODO make a method to build a payload for SET STIMULUS given each of the bits as parameters. 
    # @staticmethod
    # def StimulusCommandFormat(channel,period,width,repeat,config: int) -> tuple(int) : 

    # TODO make a method to build the config flags 
    # @staticmethod
    # def StimulusConfigBits(optoElec, monoBiphasic, Simul) -> int : 