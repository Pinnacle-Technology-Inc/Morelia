# local imports 
from Morelia.Devices import AquisitionDevice, Pod
from Morelia.packet.data import DataPacket8206HR
from Morelia.packet import ControlPacket
from Morelia.Commands import CommandSet
import Morelia.packet.conversion as conv
import time

from functools import partial
from Morelia.Devices.BasicPodProtocol import BasicPodProtocol

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "James Hurd"
__credits__     = ["Thresa Kelly", "Seth Gabbert", "James Hurd"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Pod8206HR(AquisitionDevice) : 
    """
    Pod8206HR is used to interact with a 8206HR data aquisition device.

    :param port: Serial port to be opened. Used when initializing the COM_io instance.
    :param preamp_gain: A unitless number used to add gain to vlues recived from the preamplifier. Used in converting streaming data from the device into something human-readable. Must be 10 or 100.
    :param baudrate: Baud rate of the opened serial port. Default value is 9600.
    :param device_name: Virtual name used to indentify device.
   """ 

    def __init__(self, port: str|int, preamp_gain: int, baudrate:int=9600, device_name: str | None =  None) -> None :

        # initialize POD_Basics
        super().__init__(port, 2000, baudrate, device_name) 

        # get constants for adding commands 
        UINT8  = Pod.get_u(8)
        UINT16 = Pod.get_u(16)
        BINARY_4  = 8

        # remove unimplemented commands 
        self._commands.remove_command(5)  # STATUS
        self._commands.remove_command(11) # BINARY

        # add device specific commands
        self._commands.add_command(102, 'GET LOWPASS',          (UINT8,),      (UINT16,),    False,   'Gets the lowpass filter for the desired channel (0 = EEG1, 1 = EEG2, 2 = EEG3/EMG). Returns the value in Hz.')
        self._commands.add_command(103, 'SET LOWPASS',          (UINT8,UINT16),   (0,),      False,   'Sets the lowpass filter for the desired channel (0 = EEG1, 1 = EEG2, 2 = EEG3/EMG) to the desired value (11 - 500) in Hz.')
        self._commands.add_command(104, 'SET TTL OUT',          (UINT8,UINT8),    (0,),      False,   'Sets the selected TTL pin (0,1,2,3) to an output and sets the value (0-1).')
        self._commands.add_command(105, 'GET TTL IN',           (UINT8,),      (UINT8,),     False,   'Sets the selected TTL pin (0,1,2,3) to an input and returns the value (0-1).')
        self._commands.add_command(106, 'GET TTL PORT',         (0,),       (UINT8,),     False,   'Gets the value of the entire TTL port as a byte. Does not modify pin direction.')
        self._commands.add_command(107, 'GET FILTER CONFIG',    (0,),       (UINT8,),     False,   'Gets the hardware filter configuration. 0=SL, 1=SE (Both 40/40/100Hz lowpass), 2 = SE3 (40/40/40Hz lowpas).')
        self._commands.add_command(180, 'BINARY4 DATA ',        (0,),       (BINARY_4,),     True,    'Binary4 data packets, enabled by using the STREAM command with a \'1\' argument.') # see _read_binary()
        
        """Add new commands for additional properties -- need to check how they correspond with the POD commands

        self._commands.add_command(110, 'GET NOTCH FILTER', (0,), (UINT8,), False, 'Get notch filter enabled state.')
        self._commands.add_command(111, 'SET NOTCH FILTER', (UINT8,), (0,), False, 'Set notch filter enabled state.')
        self._commands.add_command(112, 'GET NOTCH FREQUENCY', (0,), (UINT16,), False, 'Get notch filter frequency.')
        self._commands.add_command(113, 'SET NOTCH FREQUENCY', (UINT16,), (0,), False, 'Set notch filter frequency.')
        
        # TTL event enable/disable commands
        self._commands.add_command(114, 'GET ENABLE TTL IN RISE EVENT', (UINT8,), (UINT8,), False, 'Get TTL in rise event enabled.')
        self._commands.add_command(115, 'SET ENABLE TTL IN RISE EVENT', (UINT8, UINT8), (0,), False, 'Set TTL in rise event enabled.')
        self._commands.add_command(116, 'GET ENABLE TTL IN FALL EVENT', (UINT8,), (UINT8,), False, 'Get TTL in fall event enabled.')
        self._commands.add_command(117, 'SET ENABLE TTL IN FALL EVENT', (UINT8, UINT8), (0,), False, 'Set TTL in fall event enabled.')
        self._commands.add_command(118, 'GET ENABLE DEBOUNCE', (0,), (UINT8,), False, 'Get debounce enabled.')
        self._commands.add_command(119, 'SET ENABLE DEBOUNCE', (UINT8,), (0,), False, 'Set debounce enabled.')
        self._commands.add_command(120, 'GET ENABLE TTL OUT', (UINT8,), (UINT8,), False, 'Get TTL out enabled.')
        self._commands.add_command(121, 'SET ENABLE TTL OUT', (UINT8, UINT8), (0,), False, 'Set TTL out enabled.')

        # Add commands for channel names and TTL event strings
        self._commands.add_command(130, 'GET CHANNEL1 NAME', (0,), (0,), False, 'Get channel 1 name.')
        self._commands.add_command(131, 'SET CHANNEL1 NAME', (str,), (0,), False, 'Set channel 1 name.')
        self._commands.add_command(132, 'GET CHANNEL2 NAME', (0,), (0,), False, 'Get channel 2 name.')
        self._commands.add_command(133, 'SET CHANNEL2 NAME', (str,), (0,), False, 'Set channel 2 name.')
        self._commands.add_command(134, 'GET CHANNEL3 NAME', (0,), (0,), False, 'Get channel 3 name.')
        self._commands.add_command(135, 'SET CHANNEL3 NAME', (str,), (0,), False, 'Set channel 3 name.')

        self._commands.add_command(140, 'GET TTL1 EVENT STRING', (0,), (0,), False, 'Get TTL1 event string.')
        self._commands.add_command(141, 'SET TTL1 EVENT STRING', (str,), (0,), False, 'Set TTL1 event string.')
        self._commands.add_command(142, 'GET TTL2 EVENT STRING', (0,), (0,), False, 'Get TTL2 event string.')
        self._commands.add_command(143, 'SET TTL2 EVENT STRING', (str,), (0,), False, 'Set TTL2 event string.')
        self._commands.add_command(144, 'GET TTL3 EVENT STRING', (0,), (0,), False, 'Get TTL3 event string.')
        self._commands.add_command(145, 'SET TTL3 EVENT STRING', (str,), (0,), False, 'Set TTL3 event string.')
        self._commands.add_command(146, 'GET TTL4 EVENT STRING', (0,), (0,), False, 'Get TTL4 event string.')
        self._commands.add_command(147, 'SET TTL4 EVENT STRING', (str,), (0,), False, 'Set TTL4 event string.')
        """
        # preamplifier gain (should be 10x or 100x)
        if(preamp_gain != 10 and preamp_gain != 100):
            raise Exception('[!] Preamplifier gain must be 10 or 100.')
        self._preamp_gain : int = preamp_gain 
        
        # define function used to decode packet from binary data.
        def decode_packet(command_number: int, payload: bytes) -> tuple:
            if command_number == 106:
                return Pod8206HR._translate_ttlbyte_ascii(payload)

            return ControlPacket.decode_payload_from_cmd_set(self._commands, command_number, payload)
        
        # the constructor used to create control packets as they are recieved.
        self._control_packet_factory = partial(ControlPacket, decode_packet)

    @property
    def lowpass_ch0(self) -> int:
        """Gets the lowpass filter for the desired channel (0 = EEG1). Returns the value in Hz."""
        ch0_lowpass = self.write_read("GET LOWPASS", (0, ))
        return ch0_lowpass.payload[0]

    @lowpass_ch0.setter
    def lowpass_ch0(self, value: int) -> None:
        """Sets the lowpass filter for the desired channel (0 = EEG1) to the desired value (11 - 500) in Hz."""
        self.write_packet("SET LOWPASS", (0, value))

    @property
    def lowpass_ch1(self) -> int:
        """Gets the lowpass filter for the desired channel (1 = EEG2). Returns the value in Hz."""
        ch1_lowpass = self.write_read("GET LOWPASS", (1, ))
        return ch1_lowpass.payload[0]

    @lowpass_ch1.setter
    def lowpass_ch1(self, value: int) -> None:
        """Sets the lowpass filter for the desired channel (1 = EEG2) to the desired value (11 - 500) in Hz."""
        self.write_packet("SET LOWPASS", (1, value))

    @property
    def lowpass_ch2(self) -> int:
        """Gets the lowpass filter for the desired channel (2 = EEG3/EMG). Returns the value in Hz."""
        ch2_lowpass = self.write_read("GET LOWPASS", (2, ))
        return ch2_lowpass.payload[0]

    @lowpass_ch2.setter
    def lowpass_ch2(self, value: int) -> None:
        """Sets the lowpass filter for the desired channel (2 = EEG3/EMG) to the desired value (11 - 500) in Hz."""
        self.write_packet("SET LOWPASS", (2, value))

    @property
    def ttl_pin0(self) -> int:  
        """Gets the selected TTL pin (0,1,2,3) input and returns the value (0-1)."""
        p0_ttl = self.write_read("GET TTL IN", (0, ))
        return p0_ttl.payload[0]

    @ttl_pin0.setter
    def ttl_pin0(self, value: int) -> None:
        """Sets the selected TTL pin (0,1,2,3) to an output and sets the value (0-1)."""
        self.write_packet("SET TTL OUT", (0, value))


    @property
    def ttl_pin1(self) -> int:  
        """Gets the selected TTL pin (0,1,2,3) input and returns the value (0-1)."""
        p1_ttl = self.write_read("GET TTL IN", (1, ))
        return p1_ttl.payload[0]

    @ttl_pin1.setter
    def ttl_pin1(self, value: int) -> None:
        """Sets the selected TTL pin (0,1,2,3) to an output and sets the value (0-1)."""
        self.write_packet("SET TTL OUT", (1, value))

    @property
    def ttl_pin2(self) -> int:  
        """Gets the selected TTL pin (0,1,2,3) input and returns the value (0-1)."""
        p2_ttl = self.write_read("GET TTL IN", (2, ))
        return p2_ttl.payload[0]

    @ttl_pin2.setter
    def ttl_pin2(self, value: int) -> None:
        """Sets the selected TTL pin (0,1,2,3) to an output and sets the value (0-1)."""
        self.write_packet("SET TTL OUT", (2, value))

    @property
    def ttl_pin3(self) -> int:  
        """Gets the selected TTL pin (0,1,2,3) input and returns the value (0-1)."""
        p3_ttl = self.write_read("GET TTL IN", (3, ))
        return p3_ttl.payload[0]

    @ttl_pin3.setter
    def ttl_pin3(self, value: int) -> None:
        """Sets the selected TTL pin (0,1,2,3) to an output and sets the value (0-1)."""
        self.write_packet("SET TTL OUT", (3, value))
    
    @property
    def ttl_port(self) -> int:
        """Gets the value of the entire TTL port as a byte. Does not modify pin direction."""
        port = self.write_read("GET TTL PORT")
        return port.payload[0]

    @property 
    def filter_config(self) -> int: 
        """Gets the hardware filter configuration. 0=SL, 1=SE (Both 40/40/100Hz lowpass), 2 = SE3 (40/40/40Hz lowpass)."""
        config = self.write_read("GET FILTER CONFIG")
        return config.payload[0]

    # === Notch Filter ===
    @property
    def notch_filter(self) -> bool:
        """Gets the notch filter enabled state."""
        notch_status = self.write_read("GET NOTCH").payload[0]
        is_notch_enabled = notch_status == "ENABLED"
        return is_notch_enabled

    @notch_filter.setter
    def notch_filter(self, value: bool):
        """Sets the notch filter enabled state."""
        self.write_packet("SET NOTCH", "ENABLED" if value else "DISABLED")

    @property
    def notch_frequency(self) -> float:
        """Gets the notch filter frequency."""
        notch_freq_str = self.write_read("GET NOTCHFREQ").payload[0]
        notch_freq = float(notch_freq_str)
        return notch_freq

    @notch_frequency.setter
    def notch_frequency(self, value: float):
        """Sets the notch filter frequency."""
        self.write_packet("SET NOTCHFREQ", str(value))

    # === TTL Control ===
    @property
    def enable_ttl_in_rise_event(self) -> bool:
        """Gets the TTL in rise event enabled state."""
        ttl_rise_state = self.write_read("GET TTLRISE").payload[0]
        is_rise_enabled = ttl_rise_state == "ENABLED"
        return is_rise_enabled

    @enable_ttl_in_rise_event.setter
    def enable_ttl_in_rise_event(self, value: bool):
        """Sets the TTL in rise event enabled state."""
        self.write_packet("SET TTLRISE", "ENABLED" if value else "DISABLED")

    @property
    def enable_ttl_in_fall_event(self) -> bool:
        """Gets the TTL in fall event enabled state."""
        ttl_fall_state = self.write_read("GET TTLFALL").payload[0]
        is_fall_enabled = ttl_fall_state == "ENABLED"
        return is_fall_enabled

    @enable_ttl_in_fall_event.setter
    def enable_ttl_in_fall_event(self, value: bool):
        """Sets the TTL in fall event enabled state."""
        self.write_packet("SET TTLFALL", "ENABLED" if value else "DISABLED")

    @property
    def enable_debounce(self) -> bool:
        """Gets the debounce enabled state."""
        debounce_status = self.write_read("GET DEBOUNCE").payload[0]
        is_debounce_enabled = debounce_status == "ENABLED"
        return is_debounce_enabled

    @enable_debounce.setter
    def enable_debounce(self, value: bool):
        """Sets the debounce enabled state."""
        self.write_packet("SET DEBOUNCE", "ENABLED" if value else "DISABLED")

    @property
    def enable_ttl_out(self) -> bool:
        """Gets the TTL out enabled state."""
        ttl_out_status = self.write_read("GET TTLOUT").payload[0]
        is_ttl_out_enabled = ttl_out_status == "ENABLED"
        return is_ttl_out_enabled

    @enable_ttl_out.setter
    def enable_ttl_out(self, value: bool):
        """Sets the TTL out enabled state."""
        self.write_packet("SET TTLOUT", "ENABLED" if value else "DISABLED")

    # === Channel Names ===
    @property
    def channel1_name(self) -> str:
        """Gets the name of channel 1."""
        channel1_name_value = self.write_read("GET CH1NAME").payload[0]
        return channel1_name_value

    @channel1_name.setter
    def channel1_name(self, value: str):
        """Sets the name of channel 1."""
        self.write_packet("SET CH1NAME", value)

    @property
    def channel2_name(self) -> str:
        """Gets the name of channel 2."""
        channel2_name_value = self.write_read("GET CH2NAME").payload[0]
        return channel2_name_value

    @channel2_name.setter
    def channel2_name(self, value: str):
        """Sets the name of channel 2."""
        self.write_packet("SET CH2NAME", value)

    @property
    def channel3_name(self) -> str:
        """Gets the name of channel 3."""
        channel3_name_value = self.write_read("GET CH3NAME").payload[0]
        return channel3_name_value

    @channel3_name.setter
    def channel3_name(self, value: str):
        """Sets the name of channel 3."""
        self.write_packet("SET CH3NAME", value)

    # === TTL Event Strings ===
    @property
    def ttl1_event_string(self) -> str:
        """Gets the TTL1 event string."""
        ttl1_event_str = self.write_read("GET TTL1EVENT").payload[0]
        return ttl1_event_str

    @ttl1_event_string.setter
    def ttl1_event_string(self, value: str):
        """Sets the TTL1 event string."""
        self.write_packet("SET TTL1EVENT", value)

    @property
    def ttl2_event_string(self) -> str:
        """Gets the TTL2 event string."""
        ttl2_event_str = self.write_read("GET TTL2EVENT").payload[0]
        return ttl2_event_str

    @ttl2_event_string.setter
    def ttl2_event_string(self, value: str):
        """Sets the TTL2 event string."""
        self.write_packet("SET TTL2EVENT", value)

    @property
    def ttl3_event_string(self) -> str:
        """Gets the TTL3 event string."""
        ttl3_event_str = self.write_read("GET TTL3EVENT").payload[0]
        return ttl3_event_str

    @ttl3_event_string.setter
    def ttl3_event_string(self, value: str):
        """Sets the TTL3 event string."""
        self.write_packet("SET TTL3EVENT", value)

    @property
    def ttl4_event_string(self) -> str:
        """Gets the TTL4 event string."""
        ttl4_event_str = self.write_read("GET TTL4EVENT").payload[0]
        return ttl4_event_str

    @ttl4_event_string.setter
    def ttl4_event_string(self, value: str):
        """Sets the TTL4 event string."""
        self.write_packet("SET TTL4EVENT", value)

    # === TTL Per-Channel States ===
    @property
    def ttl1_rising_state(self) -> bool:
        """Gets the TTL1 rising edge detection state."""
        ttl1_rise_status = self.write_read("GET TTL1RISE").payload[0]
        return ttl1_rise_status == "ENABLED"

    @ttl1_rising_state.setter
    def ttl1_rising_state(self, value: bool):
        """Sets the TTL1 rising edge detection state."""
        self.write_packet("SET TTL1RISE", "ENABLED" if value else "DISABLED")

    @property
    def ttl2_rising_state(self) -> bool:
        """Gets the TTL2 rising edge detection state."""
        ttl2_rise_status = self.write_read("GET TTL2RISE").payload[0]
        return ttl2_rise_status == "ENABLED"

    @ttl2_rising_state.setter
    def ttl2_rising_state(self, value: bool):
        """Sets the TTL2 rising edge detection state."""
        self.write_packet("SET TTL2RISE", "ENABLED" if value else "DISABLED")

    @property
    def ttl3_rising_state(self) -> bool:
        """Gets the TTL3 rising edge detection state."""
        ttl3_rise_status = self.write_read("GET TTL3RISE").payload[0]
        return ttl3_rise_status == "ENABLED"

    @ttl3_rising_state.setter
    def ttl3_rising_state(self, value: bool):
        """Sets the TTL3 rising edge detection state."""
        self.write_packet("SET TTL3RISE", "ENABLED" if value else "DISABLED")

    @property
    def ttl4_rising_state(self) -> bool:
        """Gets the TTL4 rising edge detection state."""
        ttl4_rise_status = self.write_read("GET TTL4RISE").payload[0]
        return ttl4_rise_status == "ENABLED"

    @ttl4_rising_state.setter
    def ttl4_rising_state(self, value: bool):
        """Sets the TTL4 rising edge detection state."""
        self.write_packet("SET TTL4RISE", "ENABLED" if value else "DISABLED")

    @property
    def ttl1_falling_state(self) -> bool:
        """Gets the TTL1 falling edge detection state."""
        ttl1_fall_status = self.write_read("GET TTL1FALL").payload[0]
        return ttl1_fall_status == "ENABLED"

    @ttl1_falling_state.setter
    def ttl1_falling_state(self, value: bool):
        """Sets the TTL1 falling edge detection state."""
        self.write_packet("SET TTL1FALL", "ENABLED" if value else "DISABLED")

    @property
    def ttl2_falling_state(self) -> bool:
        """Gets the TTL2 falling edge detection state."""
        ttl2_fall_status = self.write_read("GET TTL2FALL").payload[0]
        return ttl2_fall_status == "ENABLED"

    @ttl2_falling_state.setter
    def ttl2_falling_state(self, value: bool):
        """Sets the TTL2 falling edge detection state."""
        self.write_packet("SET TTL2FALL", "ENABLED" if value else "DISABLED")

    @property
    def ttl3_falling_state(self) -> bool:
        """Gets the TTL3 falling edge detection state."""
        ttl3_fall_status = self.write_read("GET TTL3FALL").payload[0]
        return ttl3_fall_status == "ENABLED"

    @ttl3_falling_state.setter
    def ttl3_falling_state(self, value: bool):
        """Sets the TTL3 falling edge detection state."""
        self.write_packet("SET TTL3FALL", "ENABLED" if value else "DISABLED")

    @property
    def ttl4_falling_state(self) -> bool:
        """Gets the TTL4 falling edge detection state."""
        ttl4_fall_status = self.write_read("GET TTL4FALL").payload[0]
        return ttl4_fall_status == "ENABLED"

    @ttl4_falling_state.setter
    def ttl4_falling_state(self, value: bool):
        """Sets the TTL4 falling edge detection state."""
        self.write_packet("SET TTL4FALL", "ENABLED" if value else "DISABLED")

    @property
    def ttl1_debounce(self) -> bool:
        """Gets the TTL1 debounce status."""
        ttl1_debounce_status = self.write_read("GET TTL1DEBOUNCE").payload[0]
        return ttl1_debounce_status == "ENABLED"

    @ttl1_debounce.setter
    def ttl1_debounce(self, value: bool):
        """Sets the TTL1 debounce status."""
        self.write_packet("SET TTL1DEBOUNCE", "ENABLED" if value else "DISABLED")

    @property
    def ttl1_synchronous(self) -> bool:
        ttl1_sync_status = self.write_read("GET TTL1SYNCH").payload[0]
        return ttl1_sync_status == "ENABLED"

    @ttl1_synchronous.setter
    def ttl1_synchronous(self, value: bool):
        self.write_packet("SET TTL1SYNCH", "ENABLED" if value else "DISABLED")

    @staticmethod
    def _translate_ttlbyte_ascii(ttl_byte: bytes) -> dict[str,int] : 
        """Separates the bits of each TTL (0-3) from a ASCII encoded byte.

        :param ttl_byte: One byte string for the TTL (ASCII encoded).

        :return: Dictionary of the TTLs. Values are 1 when input, 0 when output.
        """
        # TTL : b 0123 XXXX <-- 8 bits, lowest 4 are always 0 (dont care=X), msb is TTL0
        return ( {
            'TTL1' : conv.ascii_bytes_to_int_split(ttl_byte, 8, 7), # TTL 0 
            'TTL2' : conv.ascii_bytes_to_int_split(ttl_byte, 7, 6), # TTL 1 
            'TTL3' : conv.ascii_bytes_to_int_split(ttl_byte, 6, 5), # TTL 2 
            'TTL4' : conv.ascii_bytes_to_int_split(ttl_byte, 5, 4)  # TTL 3 
        }, )   

    def _read_binary(self, pre_packet: bytes, validate_checksum:bool=True) -> DataPacket8206HR :
        """After receiving the pre_packet, it reads the 8 bytes(TTL+channels) and then reads to ETX (checksum+ETX). 
        See the documentation of ``DataPacket8206HR`` for my details on what this packet looks like at a protocol level.

        :param pre_packet: Bytes string containing the beginning of a POD packet: STX (1 byte) + command number (4 bytes).
        :param validate_checksum: Set to True to validate the checksum. Set to False to skip validation. Defaults to True.

        :return: Binary4 (8206HR data) POD packet.
        """

        # get prepacket + packet number, TTL, and binary ch0-2 (these are all binary, do not search for STX/ETX) + read csm and ETX (3 bytes) (these are ASCII, so check for STX/ETX)
        packet = pre_packet + self._port.read(8) + self._read_to_etx(validate_checksum=validate_checksum)
        # check if checksum is correct 
        if(validate_checksum):
            if(not self._validate_checksum(packet) ) :
                raise Exception('Bad checksum for binary POD packet read.')
        # return complete variable length binary packet
        return DataPacket8206HR(packet, self._preamp_gain)

    def _apply_config_recursive(self, config: dict, skip_keys):
        super()._apply_config_recursive(config, skip_keys)
        # TODO: add some overriding properties if necessary like:
        # if "lowpass" in config:
        #   self.lowpass = config["LOWPASS"]

    """Maps the properties for generating a config file"""
    _property_map = {
        "lowpass": {
            "lowpass_ch0": "lowpass_ch0",
            "lowpass_ch1": "lowpass_ch1",
            "lowpass_ch2": "lowpass_ch2",
        },
        "ttl pins": {
            "ttl_pin0": "ttl_pin0",
            "ttl_pin1": "ttl_pin1",
            "ttl_pin2": "ttl_pin2",
            "ttl_pin3": "ttl_pin3",
            "ttl_port": "ttl_port",
        },
        "filter config": {
            "filter_config": "filter_config",
        },
        "channel settings": {
            "notch_filter": "notch_filter",
            "notch_frequency": "notch_frequency",
        },
        "ttl events": {
            "enable_ttl_in_rise_event": "enable_ttl_in_rise_event",
            "enable_ttl_in_fall_event": "enable_ttl_in_fall_event",
            "enable_debounce": "enable_debounce",
            "enable_ttl_out": "enable_ttl_out",
        },
        "ttl labels": {
            "ttl1_event_string": "ttl1_event_string",
            "ttl2_event_string": "ttl2_event_string",
            "ttl3_event_string": "ttl3_event_string",
            "ttl4_event_string": "ttl4_event_string",
        },
        "channel names": {
            "channel1_name": "channel1_name",
            "channel2_name": "channel2_name",
            "channel3_name": "channel3_name",
        },
        "ttl states": {
            "ttl1_rising_state": "ttl1_rising_state",
            "ttl2_rising_state": "ttl2_rising_state",
            "ttl3_rising_state": "ttl3_rising_state",
            "ttl4_rising_state": "ttl4_rising_state",
            "ttl1_falling_state": "ttl1_falling_state",
            "ttl2_falling_state": "ttl2_falling_state",
            "ttl3_falling_state": "ttl3_falling_state",
            "ttl4_falling_state": "ttl4_falling_state",
            "ttl1_debounce": "ttl1_debounce",
            "ttl1_synchronous": "ttl1_synchronous",
        },
    }

    def _init_property_map(self):
        """Initializes the property map for this device. This is used to generate a config file."""
        self._property_map = self.combine_property_maps(
            self._property_map,
            self._device_property_map
        )

