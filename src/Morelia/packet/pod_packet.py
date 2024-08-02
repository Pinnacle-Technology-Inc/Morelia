from functools import cache
import Morelia.packet.conversion as conversion

class PodPacket:
    
    __slots__ = '_raw_packet'
    def __init__(self, raw_packet: bytes) -> None:
        self._raw_packet = raw_packet
        self._min_length = 2
    
    @property
    @cache
    def command_number(self) -> int:
        
        #expecting: STX + 4 bytes of command number + other + ETX
        if len(self._raw_packet) < self._min_length + 4:
            raise AttributeError(f'Packet {self._raw_packet} is improperly formatted, and command number could not be parsed. Likely cause: packet is too short.')
        
        try:
            return conversion.ascii_bytes_to_int(self._raw_packet[1:5])
        
        #maybe catch this?
#        except UnicodeDecodeError:

        except ValueError:
            raise ValueError(f'Packet has invalid command number: {self._raw_packet[1:5].decode("ascii")}.')

    
