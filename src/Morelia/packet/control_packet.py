from typing import Callable
from functools import partial

from Morelia.packet.pod_packet import PodPacket
import Morelia.packet.conversion as conv

from Morelia.Commands import CommandSet


class ControlPacket(PodPacket):
    """ Class for parsing "Standard" POD packets from raw bytes. These are associated with controlling or configuring a device, hence the name
    These packets take the following form

    .. image:: _static/control_packet.png


    The payload is normally several values that need to parsed into a tuple of integers.
    Oftentimes, this class is used a "factory" of sorts. For any given device, you might partially apply the constructor with the
    ``decode_from`` argument, and then any time you need to make a packet, just call the curried constructor with
    the raw bytes of the packet you want to parse. For a concrete example of this, see the constructor of the ``Pod8206HR`` class.

    :param decode_from: Instructs the packet how to parse the payload from raw bytes to a Python object. If a ``CommandSet`` object is passed,
        the payload is decoded according to that. Otherwise, a function must be passed that takes a command number and ``bytes`` object to decode,
        and returns a ``tuple``. For a simple example of how passing a ``decode_from`` function directly may be used,
        see the constructor of the ``Pod8206HR`` class.

    :param raw_packet: The raw bytes to be parsed as a control packet.
    """

    def __init__(self, decode_from: CommandSet | Callable[[int, bytes], tuple], raw_packet: bytes) -> None:
        super().__init__(raw_packet, min_length=8)
        
        if isinstance(decode_from, CommandSet):
            #If a command set is passed, create a decoding function by currying the command set. This way, we have a decoding function that satisfies
            #the function prototype we expect.
            self._decode_payload: Callable[[int, bytes], tuple] = partial(ControlPacket.decode_payload_from_cmd_set, decode_from)
        else:
            self._decode_payload: Callable[[int, bytes], tuple] = decode_from

        #Since the payload is parsed lazily, initialize the payload as nothing.
        self._payload: tuple | None = None

    @property
    def payload(self) -> tuple:
        """Parses the packet payload in a lazy, memoized fashion.
        
        :return: The parsed payload as a tuple.
        """
        
        #If payload has already been parsed, so need to do it again.
        if self._payload is not None:
            return self._payload
        
        if not len(self._raw_packet) - self._min_length > 0:
            #NOTE: This function used to return an empty tuple in the case that the bytes were too short, so old tests that rely on this behavior might break.
            raise ValueError('Not enough bytes to construct a control packet!')
        
        #Decode the payload and set it. The indexing is decided based on the packet structure detailed above.
        self._payload = self._decode_payload(self.command_number, self._raw_packet[5:len(self._raw_packet)-3])

        return self._payload

    @staticmethod    
    def decode_payload_from_cmd_set(cmds: CommandSet, cmd_number: int, payload: bytes) -> tuple:
        """
        Used for parsing packet payloads according to a ``CommandSet`` object. Do not use this function for payload access (it lacks the memoization that makes the payload
        property speedy), but for building bespoke decoding functions to pass to this class as ``decode_from``. 
        Generally, this function is used to create decoding functions that default to using a command set,
        but have the capability to handle edge-cases on a per-command basis. For an example of how this is used, see the constructor of the ``Pod8206HR`` class.

        :param cmds: The CommandSet to decode from.
        :param cmd_number: Command number of the packet that the payload corresponds to.
        :param payload: Raw bytes of the payload you wish to decode.
        :return: The parsed payload as a tuple.
        """
        
        #get a tuple of sizes (in bytes) each argument is expected to have, in order.
        arg_sizes: tuple[int] = cmds.argument_hex_char(cmd_number)

        #get a tuple of sizes (in bytes) each element of the return value is expected to have, in order.
        retval_sizes: tuple[int] = cmds.return_hex_char(cmd_number)
        
        #If the total size of the arguments is equal to the length of the payload, this must be an outgoing packet. Therefore, parse as such.
        if sum(arg_sizes) == len(payload):
            sizes = arg_sizes

        #If the total size of the return value is equal to the length of the payload, this must be an incoming packet. Therefore, parse as such.
        elif sum(retval_sizes) == len(payload):
            sizes = retval_sizes
        
        #If neither match, we assume the payload is just one big element. Therefore, we parse as just one element.
        else:
            sizes = (len(payload),)
        
        #List to hold the values of each element of the payload as we parse them.
        payload_values: list[sizes] = []
        
        start_byte_idx: int = 0
        
        #Loop though each expected element in the payload, and parse it to an integer.
        for size in sizes:
            end_byte_idx: int = start_byte_idx + size
            payload_values.append(conv.ascii_bytes_to_int(payload[start_byte_idx:end_byte_idx]))
            start_byte_idx = end_byte_idx

        return tuple(payload_values)
