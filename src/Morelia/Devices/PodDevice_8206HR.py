# local imports 
from Morelia.Devices import AquisitionDevice, Pod
from Morelia.packet.data import DataPacket8206HR
from Morelia.packet import ControlPacket
from Morelia.Commands import CommandSet
import Morelia.packet.conversion as conv
import time

from functools import partial

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
    def lowpass(self) -> dict[int, int]:
        """Return a dict mapping each channel to its current lowpass filter value."""
        lowpass_values = {}
        for channel in range(3):
            packet = self.write_read("GET LOWPASS", (channel,))
            value = packet.payload[0] if isinstance(packet, ControlPacket) else packet[0]
            # Get the numeric value in Hz
            lowpass_values[channel] = value
        return lowpass_values

    @lowpass.setter 
    def lowpass(self, channel_value_list: list[str] | list[tuple[int, int]]) -> None:
        """
        Accepts a list of strings like ["0:500", "1:200", ...] or a list of tuples [(0,500),         (1,200), ...] and sends SET LOWPASS commands for each.
        """
        if not isinstance(channel_value_list, list):
            raise ValueError("Expected a list of channel-value pairs for lowpass")

        for item in channel_value_list:
            if isinstance(item, str):
                channel_str, value_str = item.split(":")
                channel = int(channel_str.strip())
                value = int(value_str.strip())
            elif isinstance(item, (tuple, list)) and len(item) == 2:
                channel, value = item
            else:
                raise ValueError(f"Invalid lowpass item: {item}")
            # Send command for each channel-value pair
            self.write_packet("SET LOWPASS", (channel, value))

    @property
    def ttl(self) -> dict[int, int]:
        """Return a dic mapping of each pin to its current value"""
        ttl_values = {}
        for pin in range(4):
            packet = self.write_read("GET TTL IN", (pin, ))
            value = packet.payload[0] if isinstance(packet, ControlPacket) else packet[0]
            # Get the current value (0-1)
            ttl_values[pin] = value
        return ttl_values

    @ttl.setter 
    def ttl(self, pin_value_list: list[str] | list[tuple[int, int]]) -> None:
        """
        Accepts a list of strings or a list of tuples and sends SET TTL OUT command for each.
        """
        if not isinstance(pin_value_list, list):
            raise ValueError("Expected a list of channel-value pairs for lowpass")

        for item in pin_value_list:
            if isinstance(item, str):
                pin_str, value_str = item.split(":")
                pin = int(pin_str.strip())
                value = int(value_str.strip())
            elif isinstance(item, (tuple, list)) and len(item) == 2:
                pin, value = item
            else:
                raise ValueError(f"Invalid lowpass item: {item}")

            # Send command for each channel-value pair
            self.write_packet("SET TTL OUT", (pin, value))

    @property
    def ttl_port(self) -> int:
        port = self.write_read("GET TTL PORT")
        return port[0]

    @property 
    def filter_config(self) -> int: 
        config = self.write_read("GET FILTER CONFIG")
        return config[0]

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
        # some overriding properties like:
        # if "lowpass" in config:
        #   self.lowpass = config["LOWPASS"]
