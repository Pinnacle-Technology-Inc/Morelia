import Morelia.packet.conversion as conversion

class PodPacket:
    
    __slots__ = ('_raw_packet', '_min_length', '_command_number')
    
    #min length: STX + 4 byte command number + ETX
    def __init__(self, raw_packet: bytes, min_length: int = 6) -> None:
        self._raw_packet = raw_packet
        self._min_length = min_length

        self._command_number = None
    
    @property
    def command_number(self) -> int:
        
        if self._command_number is None:
            #expecting: STX + 4 bytes of command number + other + ETX
            if len(self._raw_packet) < self._min_length:
                raise AttributeError(f'Packet {self._raw_packet} is improperly formatted, and command number could not be parsed. Likely cause: packet is too short.')
            
            try:
                self._command_number = conversion.ascii_bytes_to_int(self._raw_packet[1:5])

            except ValueError:
                raise ValueError(f'Packet has invalid command number: {self._raw_packet[1:5].decode("ascii")}.')

        return self._command_number

    def __eq__(self, other):
        return self._raw_packet == other._raw_packet

    def __neq__(self, other):
        return not self == other

    
