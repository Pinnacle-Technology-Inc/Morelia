# local imports 
from PodApi.Devices import POD_Basics
from PodApi.Packets import Packet_Standard

# authorship
__author__      = "Sree Kondi"
__maintainer__  = "Sree Kondi"
__credits__     = ["Sree Kondi", "Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class POD_8480SC(POD_Basics) : 
    """
    POD_8480SC handles communication using an 8480-SC POD device. 
    """

    # ============ DUNDER METHODS ============      ========================================================================================================================
    

    def __init__(self, port: str|int, baudrate: int=9600) -> None :
        """Runs when an instance is constructed. It runs the parent's initialization. Then it updates \
        the _commands to contain the appropriate command set for an 8480 POD device. 

        Args:
            port (str | int): Serial port to be opened. Used when initializing the COM_io instance.
            baudrate (int, optional): Integer baud rate of the opened serial port. Used when initializing \
                the COM_io instance. Defaults to 9600.
        """
        # initialize POD_Basics
        super().__init__(port, baudrate=baudrate) 
        # get constants for adding commands 
        U8  = POD_Basics.GetU(8)
        U16 = POD_Basics.GetU(16)
        U32 = POD_Basics.GetU(32)
        # remove unimplemented commands in POD-device 8480.
        self._commands.RemoveCommand(5)  # STATUS
        self._commands.RemoveCommand(6)  # STREAM
        self._commands.RemoveCommand(9)  # ID
        self._commands.RemoveCommand(10) # SRATE
        self._commands.RemoveCommand(11) # BINARY
        # add device specific commands
        self._commands.AddCommand( 100, 'RUN STIMULUS',         (U8,),                              (0,),                                False  , 'Requires U8 Channel.  Runs the stimulus on the selected channel (0 or 1).  Will generally be immediately followed by a 133 EVENT STIM START packet, and followed by a 134 EVENT STIM END packet after the stimulus completes.')
        self._commands.AddCommand( 101, 'GET STIMULUS',         (U8,),                              (U8, U16, U16, U16, U16, U32, U8),   False  , 'Requires U8 Channel.  Gets the current stimulus configuration for the selected channel.  See format below. ')
        self._commands.AddCommand( 102,	'SET STIMULUS',	        (U8, U16, U16, U16, U16, U32, U8),	(0,),                                False  , 'Sets the stimulus configuration on the selected channel.  See format below.')  
        self._commands.AddCommand( 108,	'GET TTL SETUP',	    (U8,),	                            (U8, U8),                            False  , 'Requires U8 channel.  Returns U8 config flags, and U8 debounce value in ms.  See below for config flags format.')
        self._commands.AddCommand( 109,	'SET TTL SETUP',	    (U8,U8, U8),	                    (U8, U8),                            False  , 'Sets the TTL setup for the channel.  Format is Channel, Config Flags, Debounce in ms.  See below for config flags format.')
        self._commands.AddCommand( 110,	'GET TTL PULLUPS',	    (0,),	                            (U8,),                               False  , 'Gets whether TTL pullups are enabled on the TTL lines.  0 = no pullups, non-zero = pullups enabled.')
        self._commands.AddCommand( 111,	'SET TTL PULLUPS',	    (U8,),	                            (0,),                                False  , 'Sets whether pullups are enabled on the TTL lines.  0 = pullups disabled, non-zero = pullups enabled.')
        self._commands.AddCommand( 116,	'GET LED CURRENT',	    (0,),	                            (U16, U16),                          False  , 'Gets the setting for LED current for both channels in mA.  CH0 CH1.')
        self._commands.AddCommand( 117, 'SET LED CURRENT',	    (U8, U16),	                        (0,),                                False  , 'Requires U8 channel.  Sets the selected channel LED current to the given value in mA, from 0-600.')
        self._commands.AddCommand( 118,	'GET ESTIM CURRENT',	(0,),	                            (U16, U16),                          False  , 'Gets the setting for the ESTIM current for both channels, in percentage.  CH0 then CH1.')
        self._commands.AddCommand( 119,	'SET ESTIM CURRENT',	(U8, U16),	                        (0,),                                False  , 'Requires U8 channel.  Sets the selected chanenl ESTIM current to the given value in percentage, from 0-100.')
        self._commands.AddCommand( 124,	'GET PREAMP TYPE',	    (0,),	                            (U16,),                              False  , 'Gets the store preamp value.')
        self._commands.AddCommand( 125,	'SET PREAMP TYPE',	    (U16,),	                            (0,),                                False  , 'Sets the preamp value, from 0-1023.  This should match the table in Sirenia, it is a 10-bit code that tells the 8401 what preamp is connected.  Only needed when used with an 8401. See table below.')
        self._commands.AddCommand( 126,	'GET SYNC CONFIG',	    (0,),	                            (U8,),                               False  , 'Gets the sync config byte.  See format below.')
        self._commands.AddCommand( 127,	'SET SYNC CONFIG',	    (U8,),	                            (0,),                                False  , 'Sets the sync config byte.  See format below.')
        # The commands below are event commands and as such are outbound only.The API should handle these commands but should not send them. 
        self._commands.AddCommand( 132,	'EVENT TTL',	        (0,),	                            (U8,),                               False  , 'Indicates a TTL event has occurred on the indicated U8 TTL input.  If debounce is non-zero then this will not occur until the debounce has completed successfully.')
        self._commands.AddCommand( 133,	'EVENT STIM START',	    (0,),	                            (U8,),                               False  , 'Indicates the start of a stimulus.  Returns U8 channel.')
        self._commands.AddCommand( 134,	'EVENT STIM STOP',	    (0,),	                            (U8,),                               False  ,'Indicates the end of a stimulus. Returns U8 channel.')
        self._commands.AddCommand( 135,	'EVENT LOW CURRENT',	(0,),	                            (U8,),                               False  , 'Indicates a low current status on one or more of the LED channels.  U8 bitmask indication which channesl have low current.  Bit 0 = Ch0, Bit 1 = Ch1.')

    # ------------ BITMASKING ------------           ------------------------------------------------------------------------------------------------------------------------

    @staticmethod
    def StimulusConfigBits(optoElec: bool, monoBiphasic: bool, Simul: bool) -> int :
        """ Incoming inputs are bitmasked into an integer value. This value is later given as part of a payload \
        to command #102 'SET STIMULUS'.
    
        Args:
            optoElec (bool): Bit  is Opto/Electrical. 
            monoBiphasic (bool): Bit 1 is Monophasic/Biphasic.
            Simul (bool): Bit 2 is Simultaneous. 

        Returns:
            int: which represents the Config flag byte in the Stimulus Command. \
                The return value is the seventh item in the payload for command 'SET STIMULUS'.
        """
        return (0 | (Simul << 2) | (monoBiphasic << 1) | (optoElec))

    
    @staticmethod
    def SyncConfigBits(sync_level: bool, sync_idle: bool, signal_trigger: bool) -> int :
        """Incoming inputs are bitmasked into an integer value. This value is later given \
        as the payload to command #127 'SET SYNC CONFIG'.

        Args:
            sync_level (bool): Bit 0 is Sync Level.
            sync_idle (bool): Bit 1 is Stimulus Triggering.
            signal_trigger (bool): Bit 2 is Signal/Trigger. 

        Returns:
            int: which represents the Sync Config Bits format value. \
        """
        return (0 | (signal_trigger << 2) | (sync_idle << 1) | (sync_level))


    @staticmethod    
    def TtlConfigBits(trigger: bool, stimtrig : bool, input_sync : bool) -> int :
        """Incoming inputs are bitmasked into an integer value. This value is later given as part of the payload to \
        command #109 'SET TTL SETUP'. This commands accepts 3 items in the payload, and the return value of this function \
        is given as the second item.

        Args:
            trigger (bool): Bit 0 is 0 for rising edge, 1 for falling edge.
            stimtrig (bool): Bit 1 is  0 for TTL event notifications, 1 for TTL inputs as triggers.
            input_sync (bool): Bit 7 is 0 for normal TTL operation, 1 for TTL pin operates as a sync output.

        Returns:
            int: which represents the TTL Config Bits Format value. \
        """
        return (0 | (input_sync << 7) | (stimtrig << 1) | (trigger))
    

    @staticmethod
    def DecodeStimulusConfigBits(config: int) -> dict :
        """Converts an integer into 3 values, representing 3 individual bits of the Stimulus Config Bits. 
            
        Args:
            config (int): an integer is passed in, and it represents the Config Flag byte. 

        Returns:
            dict: Keys as the names of the bits, the values representing values at each bit. 
        """
        return {
            'optoElec'      :  config  & 1,  
            'monoBiphasic'  : (config >> 1) & 1,  
            'Simul'         : (config >> 2) & 1
        }


    @staticmethod
    def DecodeSyncConfigBits(config: int) -> dict :
        """Converts an integer into 3 values, representing 3 individual bits of the Sync Config Bits. 
            
        Args:
            config (int): an integer is passed in, and it represents the Sync Config Flag byte. 

        Returns:
            dict: Keys as the names of the bits, the values representing values at each bit. 
        """
        return {
            'SyncLevel'     :  config  & 1,
            'SyncIdle'      : (config >> 1) & 1,
            'SignalTrigger' : (config >> 2)
        }

    @staticmethod
    def DecodeTTlConfigBits(config: int) -> dict :
        """Converts an interger into 3 values, representing 3 individual bits of the TTL Config Bits.
            
        Args:
            config (int): an integer is passed in, and it represents the TTL Setup Config Flag Byte.

        Returns:
            dict: Keys as the names of the bits, the values representing values at each bit. 
        """
        return {
            'RisingFalling'  :  config  & 1,
            'StimulusTrig'   : (config >> 1) & 1,
            'TTLInputSync'   : (config >> 7) & 1
        }
    
    # ------------ OVERWRITE ------------           ------------------------------------------------------------------------------------------------------------------------

    def ReadPODpacket(self, validateChecksum: bool = True, timeout_sec: int | float = 5) -> Packet_Standard:
        """Reads a complete POD packet, either in standard or binary format, beginning with STX and \
        ending with ETX. Reads first STX and then starts recursion. 

        Args:
            validateChecksum (bool, optional): Set to True to validate the checksum. Set to False to \
                skip validation. Defaults to True.
            timeout_sec (int|float, optional): Time in seconds to wait for serial data. \
                Defaults to 5. 

        Returns:
            Packet: POD packet beginning with STX and ending with ETX. This may be a \
                standard packet, binary packet, or an unformatted packet (STX+something+ETX). 
        """
        packet: Packet_Standard = super().ReadPODpacket(validateChecksum, timeout_sec)
        # check for special packets
        match packet.CommandNumber() : 
            case 126 : # 126 GET SYNC CONFIG
                packet.SetCustomPayload(POD_8480SC._CustomSYNCCONFIG, (packet.payload,))
            case 108 : # 108 GET TTL SETUP
                packet.SetCustomPayload(POD_8480SC._Custom108GETTTLSETUP, (packet.payload,))
            case 101 : # 101 GET STIMULUS
                packet.SetCustomPayload(POD_8480SC._CustomSTIMULUS, (packet.payload, packet.DefaultPayload()))
        return packet

    def WritePacket(self, cmd: str|int, payload:int|bytes|tuple[int|bytes]=None) -> Packet_Standard :
        """Builds a POD packet and writes it to the POD device. 

        Args:
            cmd (str | int): Command number.
            payload (int | bytes | tuple[int | bytes], optional): None when there is no payload. If there \
                is a payload, set to an integer value, bytes string, or tuple. Defaults to None.

        Returns:
            Packet_Standard: Packet that was written to the POD device.
        """
        packet: Packet_Standard = super().WritePacket(cmd, payload)
        # check for special packets
        match packet.CommandNumber() : 
            case 127: # 127 SET SYNC CONFIG
                packet.SetCustomPayload(POD_8480SC._CustomSYNCCONFIG, (packet.payload,))
            case 109 : # 109 SET TTL SETUP
                packet.SetCustomPayload(POD_8480SC._Custom109SETTTLSETUP, (packet.payload,))
            case 102 : # 102 SET STIMULUS
                packet.SetCustomPayload(POD_8480SC._CustomSTIMULUS, (packet.payload, packet.DefaultPayload()))
        return packet

    @staticmethod
    def _CustomSYNCCONFIG(payload: bytes) -> dict : 
        """Custom function to translate the sync config.

        Args:
            payload (bytes): Bytes string of the POD packet payload.

        Returns:
            dict: Keys as the names of the bits, the values representing values at each bit.
        """
        return POD_8480SC.DecodeSyncConfigBits(Packet_Standard.AsciiBytesToInt( payload[:2]))

    @staticmethod
    def _Custom108GETTTLSETUP(payload: bytes) -> tuple[int|dict] : 
        """Custom function to translate the TTL setup for command #108 GET TTL SETUP.

        Args:
            payload (bytes): Bytes string of the POD packet payload.

        Returns:
            tuple[int|dict]: Tuple of the TTL setup.
        """
        return ( POD_8480SC.DecodeTTlConfigBits(Packet_Standard.AsciiBytesToInt( payload[0:2] )), # dict
                 Packet_Standard.AsciiBytesToInt( payload[2:4]) ) # int
    
    @staticmethod
    def _Custom109SETTTLSETUP(payload: bytes) -> tuple[int|dict] :
        """Custom function to translate the TTL setup for command #109 SET TTL SETUP.

        Args:
            payload (bytes): Bytes string of the POD packet payload.

        Returns:
            tuple[int|dict]: Tuple of the TTL setup.
        """
        data: list = [ Packet_Standard.AsciiBytesToInt(payload[:2]) ]
        data.append( POD_8480SC._Custom108GETTTLSETUP(payload[2:]) )
        return tuple(data)
        
    @staticmethod
    def _CustomSTIMULUS(payload: bytes, defaultPayload: tuple) -> tuple : 
        """_summary_

        Args:
            payload (bytes): Bytes string of the POD packet payload.
            defaultPayload (tuple): Default translated payload.

        Returns:
            tuple: Tuple of the translated stimulus payload.
        """
        pld = list(defaultPayload[:-1])
        pld.append(POD_8480SC.DecodeStimulusConfigBits(Packet_Standard.AsciiBytesToInt( payload[-2:] ))) # bits part of the payload
        return tuple( pld )            