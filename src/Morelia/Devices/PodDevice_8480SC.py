# local imports 
from Morelia.Devices import Pod
from Morelia.packet import ControlPacket

from functools import partial

# authorship
__author__      = "Sree Kondi"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Sree Kondi", "Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Pod8480SC(Pod) : 
    """
    POD_8480SC handles communication using an 8480-SC POD device. 

    :param port: Serial port to be opened. Used when initializing the COM_io instance.
    :param baudrate: Baud rate of the opened serial port. Default value is 9600.
    :param device_name: Virtual name used to indentify device.
    """


    def __init__(self, port: str|int, baudrate: int=9600, device_name: str | None = None) -> None:
        """Runs when an instance is constructed. It runs the parent's initialization. Then it updates \
        the _commands to contain the appropriate command set for an 8480 POD device. 
        """
        # initialize POD_Basics
        super().__init__(port, baudrate=baudrate, device_name=device_name) 

        # get constants for adding commands 
        UINT8  = Pod.get_u(8)
        UINT16 = Pod.get_u(16)
        UINT32 = Pod.get_u(32)

        # remove unimplemented commands in POD-device 8480.
        self._commands.remove_command(5)  # STATUS
        self._commands.remove_command(6)  # STREAM
        self._commands.remove_command(9)  # ID
        self._commands.remove_command(10) # SRATE
        self._commands.remove_command(11) # BINARY

        # add device specific commands
        self._commands.add_command( 100, 'RUN STIMULUS',         (UINT8,),                              (0,),                                False  , 'Requires UINT8 Channel.  Runs the stimulus on the selected channel (0 or 1).  Will generally be immediately followed by a 133 EVENT STIM START packet, and followed by a 134 EVENT STIM END packet after the stimulus completes.')
        self._commands.add_command( 101, 'GET STIMULUS',         (UINT8,),                              (UINT8, UINT16, UINT16, UINT16, UINT16, UINT32, UINT8),   False  , 'Requires UINT8 Channel.  Gets the current stimulus configuration for the selected channel.  See format below. ')
        self._commands.add_command( 102,	'SET STIMULUS',	        (UINT8, UINT16, UINT16, UINT16, UINT16, UINT32, UINT8),	(0,),                                False  , 'Sets the stimulus configuration on the selected channel.  See format below.')  
        self._commands.add_command( 108,	'GET TTL SETUP',	    (UINT8,),	                            (UINT8, UINT8),                            False  , 'Requires UINT8 channel.  Returns UINT8 config flags, and UINT8 debounce value in ms.  See below for config flags format.')
        self._commands.add_command( 109,	'SET TTL SETUP',	    (UINT8,UINT8, UINT8),	                    (UINT8, UINT8),                            False  , 'Sets the TTL setup for the channel.  Format is Channel, Config Flags, Debounce in ms.  See below for config flags format.')
        self._commands.add_command( 110,	'GET TTL PULLUPS',	    (0,),	                            (UINT8,),                               False  , 'Gets whether TTL pullups are enabled on the TTL lines.  0 = no pullups, non-zero = pullups enabled.')
        self._commands.add_command( 111,	'SET TTL PULLUPS',	    (UINT8,),	                            (0,),                                False  , 'Sets whether pullups are enabled on the TTL lines.  0 = pullups disabled, non-zero = pullups enabled.')
        self._commands.add_command( 116,	'GET LED CURRENT',	    (0,),	                            (UINT16, UINT16),                          False  , 'Gets the setting for LED current for both channels in mA.  CH0 CH1.')
        self._commands.add_command( 117, 'SET LED CURRENT',	    (UINT8, UINT16),	                        (0,),                                False  , 'Requires UINT8 channel.  Sets the selected channel LED current to the given value in mA, from 0-600.')
        self._commands.add_command( 118,	'GET ESTIM CURRENT',	(0,),	                            (UINT16, UINT16),                          False  , 'Gets the setting for the ESTIM current for both channels, in percentage.  CH0 then CH1.')
        self._commands.add_command( 119,	'SET ESTIM CURRENT',	(UINT8, UINT16),	                        (0,),                                False  , 'Requires UINT8 channel.  Sets the selected chanenl ESTIM current to the given value in percentage, from 0-100.')
        self._commands.add_command( 124,	'GET PREAMP TYPE',	    (0,),	                            (UINT16,),                              False  , 'Gets the store preamp value.')
        self._commands.add_command( 125,	'SET PREAMP TYPE',	    (UINT16,),	                            (0,),                                False  , 'Sets the preamp value, from 0-1023.  This should match the table in Sirenia, it is a 10-bit code that tells the 8401 what preamp is connected.  Only needed when used with an 8401. See table below.')
        self._commands.add_command( 126,	'GET SYNC CONFIG',	    (0,),	                            (UINT8,),                               False  , 'Gets the sync config byte.  See format below.')
        self._commands.add_command( 127,	'SET SYNC CONFIG',	    (UINT8,),	                            (0,),                                False  , 'Sets the sync config byte.  See format below.')
        # The commands below are event commands and as such are outbound only.The API should handle these commands but should not send them. 
        self._commands.add_command( 132,	'EVENT TTL',	        (0,),	                            (UINT8,),                               False  , 'Indicates a TTL event has occurred on the indicated UINT8 TTL input.  If debounce is non-zero then this will not occur until the debounce has completed successfully.')
        self._commands.add_command( 133,	'EVENT STIM START',	    (0,),	                            (UINT8,),                               False  , 'Indicates the start of a stimulus.  Returns UINT8 channel.')
        self._commands.add_command( 134,	'EVENT STIM STOP',	    (0,),	                            (UINT8,),                               False  ,'Indicates the end of a stimulus. Returns UINT8 channel.')
        self._commands.add_command( 135,	'EVENT LOW CURRENT',	(0,),	                            (UINT8,),                               False  , 'Indicates a low current status on one or more of the LED channels.  UINT8 bitmask indication which channesl have low current.  Bit 0 = Ch0, Bit 1 = Ch1.')
        
        # function used to decode payloads of recieved control packets.
        def decode_payload(cmd_number: int, payload: bytes) -> tuple:
            match cmd_number:
                case 126 | 127:
                    return Pod8480SC._custom_sync_config(payload)

                case 108:
                    return Pod8480SC._custom_108_get_ttl_setup(payload)

                case 109:
                    return Pod8480SC._custom_109_set_ttl_setup(payload)

                case 101 | 102:
                    return Pod8480SC._custom_stimulus(payload, ControlPacket.decode_payload_from_cmd_set(self._commands, cmd_number, payload))

                case _:
                    return ControlPacket.decode_payload_from_cmd_set(self._commands, cmd_number, payload)
        
        # control packet constructor.
        self._control_packet_factory = partial(ControlPacket, decode_payload)



    @staticmethod
    def stimulus_config_bits(optoElec: bool, monoBiphasic: bool, Simul: bool) -> int :
        """ Incoming inputs are bitmasked into an integer value. This value is later given as part of a payload \
        to command #102 'SET STIMULUS'.
    
        :param optoElec: Bit  is Opto/Electrical. 
        :param monoBiphasic: Bit 1 is Monophasic/Biphasic.
        :param Simul: Bit 2 is Simultaneous. 

        :return: which represents the Config flag byte in the Stimulus Command. \
                The return value is the seventh item in the payload for command 'SET STIMULUS'.
        """
        return (0 | (Simul << 2) | (monoBiphasic << 1) | (optoElec))
    
    @staticmethod
    def sync_config_bits(sync_level: bool, sync_idle: bool, signal_trigger: bool) -> int :
        """Incoming inputs are bitmasked into an integer value. This value is later given \
        as the payload to command #127 'SET SYNC CONFIG'.

        :param sync_level: Bit 0 is Sync Level.
        :param sync_idle: Bit 1 is Stimulus Triggering.
        :param signal_trigger: Bit 2 is Signal/Trigger. 

        :return: which represents the Sync Config Bits format value. \
        """
        return (0 | (signal_trigger << 2) | (sync_idle << 1) | (sync_level))

    @staticmethod    
    def ttl_config_bits(trigger: bool, stimtrig : bool, input_sync : bool) -> int :
        """Incoming inputs are bitmasked into an integer value. This value is later given as part of the payload to \
        command #109 'SET TTL SETUP'. This commands accepts 3 items in the payload, and the return value of this function \
        is given as the second item.

        :param trigger: Bit 0 is 0 for rising edge, 1 for falling edge.
        :param stimtrig: Bit 1 is  0 for TTL event notifications, 1 for TTL inputs as triggers.
        :param input_sync: Bit 7 is 0 for normal TTL operation, 1 for TTL pin operates as a sync output.

        :return: which represents the TTL Config Bits Format value.
        """
        return (0 | (input_sync << 7) | (stimtrig << 1) | (trigger))

    @staticmethod
    def decode_stimulus_config_bits(config: int) -> dict :
        """Converts an integer into 3 values, representing 3 individual bits of the Stimulus Config Bits. 
            
        :param config: an integer is passed in, and it represents the Config Flag byte. 

        :return: Keys as the names of the bits, the values representing values at each bit. 
        """
        return {
            'optoElec'      :  config  & 1,  
            'monoBiphasic'  : (config >> 1) & 1,  
            'Simul'         : (config >> 2) & 1
        }

    @staticmethod
    def decode_sync_config_bits(config: int) -> dict :
        """Converts an integer into 3 values, representing 3 individual bits of the Sync Config Bits. 
            
        :param config: an integer is passed in, and it represents the Sync Config Flag byte. 

        :return: Keys as the names of the bits, the values representing values at each bit. 
        """
        return {
            'SyncLevel'     :  config  & 1,
            'SyncIdle'      : (config >> 1) & 1,
            'SignalTrigger' : (config >> 2)
        }

    @staticmethod
    def decode_ttl_config_bits(config: int) -> dict :
        """Converts an interger into 3 values, representing 3 individual bits of the TTL Config Bits.
            
        :param config: an integer is passed in, and it represents the TTL Setup Config Flag Byte.

        :return: Keys as the names of the bits, the values representing values at each bit. 
        """
        return {
            'RisingFalling'  :  config  & 1,
            'StimulusTrig'   : (config >> 1) & 1,
            'TTLInputSync'   : (config >> 7) & 1
        }
    
    @staticmethod
    def _custom_sync_config(payload: bytes) -> dict : 
        """Custom function to translate the sync config.

        Args:
            payload (bytes): Bytes string of the POD packet payload.

        Returns:
            dict: Keys as the names of the bits, the values representing values at each bit.
        """
        return Pod8480SC.decode_sync_config_bits(conv.ascii_bytes_to_int( payload[:2]))

    @staticmethod
    def _custom_108_get_ttl_setup(payload: bytes) -> tuple[int|dict] : 
        """Custom function to translate the TTL setup for command #108 GET TTL SETUP.

        Args:
            payload (bytes): Bytes string of the POD packet payload.

        Returns:
            tuple[int|dict]: Tuple of the TTL setup.
        """
        return ( Pod8480SC.decode_ttl_config_bits(conv.ascii_bytes_to_int( payload[0:2] )), # dict
                 conv.ascii_bytes_to_int( payload[2:4]) ) # int
    
    @staticmethod
    def _custom_109_set_ttl_setup(payload: bytes) -> tuple[int|dict] :
        """Custom function to translate the TTL setup for command #109 SET TTL SETUP.

        Args:
            payload (bytes): Bytes string of the POD packet payload.

        Returns:
            tuple[int|dict]: Tuple of the TTL setup.
        """
        data: list = [ conv.ascii_bytes_to_int(payload[:2]) ]
        data.append( Pod8480SC._custom_108_get_ttl_setup(payload[2:]) )
        return tuple(data)
        
    @staticmethod
    def _custom_stimulus(payload: bytes, default_payload: tuple) -> tuple : 
        """_summary_

        Args:
            payload (bytes): Bytes string of the POD packet payload.
            default_payload (tuple): Default translated payload.

        Returns:
            tuple: Tuple of the translated stimulus payload.
        """
        pld = list(default_payload[:-1])
        pld.append(Pod8480SC.decode_stimulus_config_bits(conv.ascii_bytes_to_int( payload[-2:] ))) # bits part of the payload
        return tuple( pld )            
        
