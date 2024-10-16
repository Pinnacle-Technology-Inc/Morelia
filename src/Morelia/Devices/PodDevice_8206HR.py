# local imports 
from Morelia.Devices import AquisitionDevice, Pod
from Morelia.packet.data import DataPacket8206HR
from Morelia.packet import ControlPacket
from Morelia.Commands import CommandSet
import Morelia.packet.conversion as conv

from functools import partial

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Pod8206HR(AquisitionDevice) : 
    """
    POD_8206HR handles communication using an 8206HR POD device. 
    
    Attributes:
        _preampGain (int): Instance-level integer (10 or 100) preamplifier gain.
    """
    
    # ------------ DUNDER ------------           ------------------------------------------------------------------------------------------------------------------------

    def __init__(self, port: str|int, preampGain: int, baudrate:int=9600, device_name: str | None =  None) -> None :
        """Runs when an instance is constructed. It runs the parent's initialization. Then it updates \
        the _commands to contain the appropriate commands for an 8206-HR POD device. 

        Args:
            port (str | int): Serial port to be opened. Used when initializing the COM_io instance.
            preampGain (int): Preamplifier gain. Must be 10 or 100.
            baudrate (int, optional): Integer baud rate of the opened serial port. Used when initializing \
                the COM_io instance. Defaults to 9600.

        Raises:
            Exception: Preamplifier gain must be 10 or 100.
        """
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
        #self._commands.AddCommand( 100, 'GET SAMPLE RATE',  (0,),       (U16,),     False,  'Gets the current sample rate of the system, in Hz.')
        #self._commands.AddCommand( 101, 'SET SAMPLE RATE',  (U16,),     (0,),       False,  'Sets the sample rate of the system, in Hz. Valid values are 2000 - 20000 currently.')
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
        
        def decode_packet(command_number: int, payload: bytes) -> tuple:
            if command_number == 106:
                return Pod8206HR._TranslateTTLbyte_ASCII(payload)

            return ControlPacket.decode_payload_from_cmd_set(self._commands, command_number, payload)

        self._control_packet_factory = partial(ControlPacket, decode_packet)

    # ------------ CONVERSIONS ------------           ------------------------------------------------------------------------------------------------------------------------


    @staticmethod
    def _TranslateTTLbyte_ASCII(ttlByte: bytes) -> dict[str,int] : 
        """Separates the bits of each TTL (0-3) from a ASCII encoded byte.

        Args:
            ttlByte (bytes): One byte string for the TTL (ASCII encoded).

        Returns:
            dict[str,int]: Dictionary of the TTLs. Values are 1 when input, 0 when output.
        """
        # TTL : b 0123 XXXX <-- 8 bits, lowest 4 are always 0 (dont care=X), msb is TTL0
        return ( {
            'TTL1' : conv.ascii_bytes_to_int_split(ttlByte, 8, 7), # TTL 0 
            'TTL2' : conv.ascii_bytes_to_int_split(ttlByte, 7, 6), # TTL 1 
            'TTL3' : conv.ascii_bytes_to_int_split(ttlByte, 6, 5), # TTL 2 
            'TTL4' : conv.ascii_bytes_to_int_split(ttlByte, 5, 4)  # TTL 3 
        }, )   


    # ------------ OVERWRITE ------------           ------------------------------------------------------------------------------------------------------------------------

    def _Read_Binary(self, prePacket: bytes, validateChecksum:bool=True) -> DataPacket8206HR :
        """After receiving the prePacket, it reads the 8 bytes(TTL+channels) and then reads to ETX \
        (checksum+ETX). 

        Args:
            prePacket (bytes): Bytes string containing the beginning of a POD packet: STX (1 byte) \
                + command number (4 bytes).
            validateChecksum (bool, optional): Set to True to validate the checksum. Set to False to \
                skip validation. Defaults to True.

        Raises:
            Exception: Bad checksum for binary POD packet read.

        Returns:
            Packet_Binary4: Binary4 POD packet.
        """

        # ------------------------------------------------------------		
        # Binary 4 Data Format
        # ------------------------------------------------------------		
        # Byte    Value	        Format      Description 
        # ------------------------------------------------------------		
        # 0	    0x02	        Binary		STX
        # 1	    0	            ASCII		Command Number Byte 0
        # 2	    0	            ASCII		Command Number Byte 1
        # 3	    B	            ASCII		Command Number Byte 2
        # 4	    4	            ASCII		Command Number Byte 3
        # 5	    Packet Number 	Binary		A rolling value that increases with each packet, and rolls over to 0 after it hits 255
        # 6	    TTL	            Binary		The byte value of the TTL port.  Value would be equivalent to the command 106 GET TTL PORT above
        # 7	    Ch0 LSB	        Binary		Least significant byte of the Channel 0 (EEG1) value
        # 8	    Ch0 MSB	        Binary		Most significant byte of the Channel 0 (EEG1) value
        # 9	    Ch1 LSB	        Binary		Channel 1 / EEG2 LSB
        # 10    Ch1 MSB	        Binary		Channel 1 / EEG2 MSB
        # 11    Ch2 LSB	        Binary		Channel 2 / EEG3/EMG LSB
        # 12    Ch2 MSB	        Binary		Channel 2 / EEG3/EMG MSB
        # 13    Checksum MSB	ASCII		MSB of checksum
        # 14    Checksum LSB	ASCII		LSB of checkxum
        # 15    0x03	        Binary		ETX
        # ------------------------------------------------------------
        
        # get prepacket + packet number, TTL, and binary ch0-2 (these are all binary, do not search for STX/ETX) + read csm and ETX (3 bytes) (these are ASCII, so check for STX/ETX)
        packet = prePacket + self._port.Read(8) + self._Read_ToETX(validateChecksum=validateChecksum)
        # check if checksum is correct 
        if(validateChecksum):
            if(not self._ValidateChecksum(packet) ) :
                raise Exception('Bad checksum for binary POD packet read.')
        # return complete variable length binary packet
        return DataPacket8206HR(packet, self._preampGain)
