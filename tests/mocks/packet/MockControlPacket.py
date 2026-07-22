import Morelia.packet.conversion as conv
from .MockPacket import MockPacket

class MockControlPacket(MockPacket):
    """
    Mock Control Packet Generator.

    Generates raw control packets compatible with ``ControlPacket`` for use in
    unit tests.

    The payload should already be encoded exactly as the device would transmit
    it (ASCII-encoded integers, binary structures, strings, etc.). This class
    simply constructs a valid POD control packet around that payload.

    Parameters
    ----------
    command_number : int
        Command number to encode.

    payload : bytes, optional
        Encoded payload bytes. Defaults to an empty payload.
    """

    def __init__(
        self,
        command_number: int,
        payload: bytes = b"",
    ):
        self.command_number = command_number
        self.payload = payload

    def to_bytes(self) -> bytes:
        stx = b"\x02"
        etx = b"\x03"

        command_number_bytes = conv.int_to_ascii_bytes(self.command_number, 4)

        # Checksum is calculated over everything after STX and before the checksum.
        checksum = self.calculate_checksum(command_number_bytes + self.payload)

        return (
            stx
            + command_number_bytes
            + self.payload
            + checksum
            + etx
        )