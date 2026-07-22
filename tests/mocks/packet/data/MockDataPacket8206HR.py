import random

import Morelia.packet.conversion as conv

from tests.mocks.packet.MockPacket import MockPacket


class MockDataPacket8206HR(MockPacket):
    """
    Mock 8401HR Data Packet Generator.

    Generates raw packets compatible with DataPacket8401HR.

    Packet format:

    STX (1 byte)
    Command number (4 ASCII bytes)
    Packet number (1 byte)
    TTL (1 byte)
    Channel 0 (2 bytes little endian)
    Channel 1 (2 bytes little endian)
    Channel 2 (2 bytes little endian)
    Checksum (2 ASCII bytes)
    ETX (1 byte)
    """

    COMMAND_NUMBER = 180

    def __init__(
        self,
        ch0=None,
        ch1=None,
        ch2=None,
        ttl1=0,
        ttl2=0,
        ttl3=0,
        ttl4=0,
        packet_number=0,
        seed=None,
    ):
        """
        Construct mock 8401HR packet.

        Parameters
        ----------
        ch0, ch1, ch2 : int
            16-bit channel ADC values.
        ttl : int
            TTL byte value.
        packet_number : int
            Rolling packet counter.
        seed : int
            Random seed for deterministic tests.
        """

        rng = random.Random(seed)

        self.ch0 = ch0 if ch0 is not None else rng.randint(0, 0xFFFF)
        self.ch1 = ch1 if ch1 is not None else rng.randint(0, 0xFFFF)
        self.ch2 = ch2 if ch2 is not None else rng.randint(0, 0xFFFF)

        self.ttl1 = bool(ttl1)
        self.ttl2 = bool(ttl2)
        self.ttl3 = bool(ttl3)
        self.ttl4 = bool(ttl4)

        self.packet_number = packet_number & 0xFF


    def to_bytes(self):
        """
        Build raw packet bytes.
        """

        stx = b"\x02"
        etx = b"\x03"

        command_number = conv.int_to_ascii_bytes(
            self.COMMAND_NUMBER,
            4
        )

        payload = bytearray(8)

        #
        # Header
        #
        ttl = (
            (0x80 if self.ttl1 else 0)
            | (0x40 if self.ttl2 else 0)
            | (0x20 if self.ttl3 else 0)
            | (0x10 if self.ttl4 else 0)
        )

        payload[0] = self.packet_number
        payload[1] = ttl

        #
        # Channels are little endian
        #
        payload[2] = self.ch0 & 0xFF
        payload[3] = (self.ch0 >> 8) & 0xFF

        payload[4] = self.ch1 & 0xFF
        payload[5] = (self.ch1 >> 8) & 0xFF

        payload[6] = self.ch2 & 0xFF
        payload[7] = (self.ch2 >> 8) & 0xFF


        #
        # Checksum covers command + payload
        #
        checksum_data = command_number + bytes(payload)
        checksum = self.calculate_checksum(checksum_data)

        return (
            stx
            + command_number
            + bytes(payload)
            + checksum
            + etx
        )