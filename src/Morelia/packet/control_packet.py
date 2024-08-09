from typing import Callable
from functools import partial

from Morelia.packet.pod_packet import PodPacket
import Morelia.packet.conversion as conv

from Morelia.Commands import CommandSet

class ControlPacket(PodPacket):
    #kinda hate this type signiture but oh well
    def __init__(self, decode_from: CommandSet, raw_packet: bytes) -> None:
        super().__init__(raw_packet, 8)

        if isinstance(decode_from, CommandSet):
            self._decode_payload: Callable[[int, bytes], tuple] = partial(ControlPacket.decode_payload_from_cmd_set, decode_from)
        else:
            self._decode_payload: Callable[[int, bytes], tuple] = decode_from


        self._payload: tuple | None = None

    @property
    def payload(self) -> tuple:

        if self._payload is not None:
            return self._payload

        if not len(self._raw_packet) - self._min_length > 0:
            #return None if no payload, would like this to be unit, but using None for legacy reasons
            return tuple()

        self._payload = self._decode_payload(self.command_number, self._raw_packet[5:len(self._raw_packet)-3])

        return self._payload

    @staticmethod    
    def decode_payload_from_cmd_set(cmds: CommandSet, cmd_number: int, payload: bytes) -> tuple:
        #don't use this for payload access, use instance.payload is read. this is for extending the functionality
        #of decoding.
        arg_sizes: tuple[int] = cmds.ArgumentHexChar(cmd_number)
        retval_sizes: tuple[int] = cmds.ReturnHexChar(cmd_number)

        if sum(arg_sizes) == len(payload):
            sizes = arg_sizes

        elif sum(retval_sizes) == len(payload):
            sizes = retval_sizes

        else:
            sizes = (len(payload),)
        
        print(sizes)
        payload_values: list[sizes] = []
        
        start_byte_idx: int = 0

        for size in sizes:
            end_byte_idx: int = start_byte_idx + size
            payload_values.append(conv.ascii_bytes_to_int(payload[start_byte_idx:end_byte_idx]))
            start_byte_idx = end_byte_idx

        return tuple(payload_values)

