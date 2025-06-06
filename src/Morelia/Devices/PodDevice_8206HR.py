# local imports 
from Morelia.Devices import AquisitionDevice, Pod
from Morelia.packet.data import DataPacket8206HR
from Morelia.packet import ControlPacket
from Morelia.Commands import CommandSet
import Morelia.packet.conversion as conv

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
    :param preampGain: A unitless number used to add gain to vlues recived from the preamplifier. Used in converting streaming data from the device into something human-readable. Must be 10 or 100.
    :param baudrate: Baud rate of the opened serial port. Default value is 9600.
    :param device_name: Virtual name used to indentify device.
   """ 

    def __init__(self, port: str|int, preampGain: int, baudrate:int=9600, device_name: str | None =  None) -> None :

        # initialize POD_Basics
        super().__init__(port, 2000, baudrate, device_name) 

        # get constants for adding commands 
        U8  = Pod.GetU(8)
        U16 = Pod.GetU(16)
        B4  = 8

        # remove unimplemented commands 
        self._commands.RemoveCommand(5)  # STATUS
        self._commands.RemoveCommand(9)  # ID
        self._commands.RemoveCommand(10) # SAMPLE RATE
        self._commands.RemoveCommand(11) # BINARY

        # add device specific commands
        self._commands.AddCommand(102, 'GET LOWPASS',          (U8,),      (U16,),    False,   'Gets the lowpass filter for the desired channel (0 = EEG1, 1 = EEG2, 2 = EEG3/EMG). Returns the value in Hz.')
        self._commands.AddCommand(103, 'SET LOWPASS',          (U8,U16),   (0,),      False,   'Sets the lowpass filter for the desired channel (0 = EEG1, 1 = EEG2, 2 = EEG3/EMG) to the desired value (11 - 500) in Hz.')
        self._commands.AddCommand(104, 'SET TTL OUT',          (U8,U8),    (0,),      False,   'Sets the selected TTL pin (0,1,2,3) to an output and sets the value (0-1).')
        self._commands.AddCommand(105, 'GET TTL IN',           (U8,),      (U8,),     False,   'Sets the selected TTL pin (0,1,2,3) to an input and returns the value (0-1).')
        self._commands.AddCommand(106, 'GET TTL PORT',         (0,),       (U8,),     False,   'Gets the value of the entire TTL port as a byte. Does not modify pin direction.')
        self._commands.AddCommand(107, 'GET FILTER CONFIG',    (0,),       (U8,),     False,   'Gets the hardware filter configuration. 0=SL, 1=SE (Both 40/40/100Hz lowpass), 2 = SE3 (40/40/40Hz lowpas).')
        self._commands.AddCommand(180, 'BINARY4 DATA ',        (0,),       (B4,),     True,    'Binary4 data packets, enabled by using the STREAM command with a \'1\' argument.') # see _Read_Binary()

        # preamplifier gain (should be 10x or 100x)
        if(preampGain != 10 and preampGain != 100):
            raise Exception('[!] Preamplifier gain must be 10 or 100.')
        self._preampGain : int = preampGain 
        
        # define function used to decode packet from binary data.
        def decode_packet(command_number: int, payload: bytes) -> tuple:
            if command_number == 106:
                return Pod8206HR._TranslateTTLbyte_ASCII(payload)

            return ControlPacket.decode_payload_from_cmd_set(self._commands, command_number, payload)
        
        # the constructor used to create control packets as they are recieved.
        self._control_packet_factory = partial(ControlPacket, decode_packet)


    @staticmethod
    def _TranslateTTLbyte_ASCII(ttlByte: bytes) -> dict[str,int] : 
        """Separates the bits of each TTL (0-3) from a ASCII encoded byte.

        :param ttlByte: One byte string for the TTL (ASCII encoded).

        :return: Dictionary of the TTLs. Values are 1 when input, 0 when output.
        """
        # TTL : b 0123 XXXX <-- 8 bits, lowest 4 are always 0 (dont care=X), msb is TTL0
        return ( {
            'TTL1' : conv.ascii_bytes_to_int_split(ttlByte, 8, 7), # TTL 0 
            'TTL2' : conv.ascii_bytes_to_int_split(ttlByte, 7, 6), # TTL 1 
            'TTL3' : conv.ascii_bytes_to_int_split(ttlByte, 6, 5), # TTL 2 
            'TTL4' : conv.ascii_bytes_to_int_split(ttlByte, 5, 4)  # TTL 3 
        }, )   

    def _Read_Binary(self, prePacket: bytes, validateChecksum:bool=True) -> DataPacket8206HR :
        """After receiving the prePacket, it reads the 8 bytes(TTL+channels) and then reads to ETX (checksum+ETX). 
        See the documentation of ``DataPacket8206HR`` for my details on what this packet looks like at a protocol level.

        :param prePacket: Bytes string containing the beginning of a POD packet: STX (1 byte) + command number (4 bytes).
        :param validateChecksum: Set to True to validate the checksum. Set to False to skip validation. Defaults to True.

        :return: Binary4 (8206HR data) POD packet.
        """

        # get prepacket + packet number, TTL, and binary ch0-2 (these are all binary, do not search for STX/ETX) + read csm and ETX (3 bytes) (these are ASCII, so check for STX/ETX)
        packet = prePacket + self._port.Read(8) + self._Read_ToETX(validateChecksum=validateChecksum)
        # check if checksum is correct 
        if(validateChecksum):
            if(not self._ValidateChecksum(packet) ) :
                raise Exception('Bad checksum for binary POD packet read.')
        # return complete variable length binary packet
        return DataPacket8206HR(packet, self._preampGain)
