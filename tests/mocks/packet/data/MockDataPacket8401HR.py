import random

import Morelia.packet.conversion as conv

from tests.mocks.packet.MockPacket import MockPacket

class MockDataPacket8401HR(MockPacket):
    """
    Mock 8401HR Data Packet Generator.

    Generates valid raw packets compatible with `DataPacket8401HR`.
    This class is intended to produce deterministic packet bytes for tests
    while exposing the same channel fields that the real device packet
    contains.
    
    STX (0x02)
    Command number (4 ASCII bytes)
    Payload (23 bytes)
    Checksum (2 ASCII bytes)
    ETX (0x03)

    Attributes
    ----------
    ch0, ch1, ch2, ch3 : int
        18-bit primary analog channel values.
    ext0, ext1 : int
        12-bit secondary analog channel values.
    ttl1, ttl2, ttl3, ttl4 : int
        12-bit TTL/auxiliary channel values.
    packet_number : int
        Packet sequence number (stored in a single byte).
    status : int
        Status byte included in the packet header.
    COMMAND_NUMBER : int
        8401HR command number used for packet generation.

    Notes
    -----
    - Primary channels are packed across 9 bytes using bit-level packing.
    - Secondary channels use 2 bytes each, with 12 bits of data stored in
      the upper nibble of the first byte and the full second byte.
    - Checksum is computed over the ASCII command number and payload.
    """

    COMMAND_NUMBER = 181

    def __init__(
        self,
        ch0=None,
        ch1=None,
        ch2=None,
        ch3=None,
        ext0=None,
        ext1=None,
        ttl1=None,
        ttl2=None,
        ttl3=None,
        ttl4=None,
        packet_number=0,
        status=0,
        seed=None,
    ):
        """
        Construct a mock 8401HR data packet.

        Parameters
        ----------
        ch0, ch1, ch2, ch3 : int, optional
            18-bit primary channel values. If omitted, random values are
            generated within the valid 0..0x3FFFF range.
        ext0, ext1 : int, optional
            12-bit secondary analog channel values. If omitted, random
            values are generated within the valid 0..0x0FFF range.
        ttl1, ttl2, ttl3, ttl4 : int, optional
            12-bit TTL/auxiliary channel values. If omitted, random values are
            generated within the valid 0..0x0FFF range.
        packet_number : int, default 0
            Sequence number stored as a single byte in the generated payload.
        status : int, default 0
            Status byte included in the payload.
        seed : int, optional
            Seed for deterministic random value generation.
        """
        rng = random.Random(seed)

        # 18-bit primary channels
        self.ch0 = ch0 if ch0 is not None else rng.randint(0, 0x3FFFF)
        self.ch1 = ch1 if ch1 is not None else rng.randint(0, 0x3FFFF)
        self.ch2 = ch2 if ch2 is not None else rng.randint(0, 0x3FFFF)
        self.ch3 = ch3 if ch3 is not None else rng.randint(0, 0x3FFFF)

        # 12-bit secondary analog channels
        self.ext0 = ext0 if ext0 is not None else rng.randint(0, 0x0FFF)
        self.ext1 = ext1 if ext1 is not None else rng.randint(0, 0x0FFF)

        self.ttl1 = ttl1 if ttl1 is not None else rng.randint(0, 0x0FFF)
        self.ttl2 = ttl2 if ttl2 is not None else rng.randint(0, 0x0FFF)
        self.ttl3 = ttl3 if ttl3 is not None else rng.randint(0, 0x0FFF)
        self.ttl4 = ttl4 if ttl4 is not None else rng.randint(0, 0x0FFF)

        self.packet_number = packet_number & 0xFF
        self.status = status & 0xFF

    def to_bytes(self):
        """
        Build the raw 8401HR packet bytes.

        Returns
        -------
        bytes
            Complete packet encoded as:
            STX + command number + payload + checksum + ETX.

        Notes
        -----
        - The command number is encoded as 4 ASCII bytes.
        - The 23-byte payload begins with packet number and status.
        - Four 18-bit primary channels are packed across bytes 2-10.
        - Six 12-bit auxiliary channels are encoded as 2 bytes each.
        - The checksum covers the ASCII command number and payload bytes.
        """

        stx = b"\x02"
        etx = b"\x03"

        command_number = conv.int_to_ascii_bytes(self.COMMAND_NUMBER, 4)

        #
        # Build payload (bytes 5-27)
        #
        payload = bytearray(23)

        payload[0] = self.packet_number
        payload[1] = self.status

        ch0 = self.ch0 & 0x3FFFF
        ch1 = self.ch1 & 0x3FFFF
        ch2 = self.ch2 & 0x3FFFF
        ch3 = self.ch3 & 0x3FFFF

        #
        # Pack the four 18-bit channels exactly as specified
        #

        payload[2] = (ch3 >> 10) & 0xFF
        payload[3] = (ch3 >> 2) & 0xFF
        payload[4] = ((ch3 & 0x03) << 6) | ((ch2 >> 12) & 0x3F)

        payload[5] = (ch2 >> 4) & 0xFF
        payload[6] = ((ch2 & 0x0F) << 4) | ((ch1 >> 14) & 0x0F)

        payload[7] = (ch1 >> 6) & 0xFF
        payload[8] = ((ch1 & 0x3F) << 2) | ((ch0 >> 16) & 0x03)

        payload[9] = (ch0 >> 8) & 0xFF
        payload[10] = ch0 & 0xFF

        #
        # 12-bit analog values
        #

        analog_channels = (
            self.ext0,
            self.ext1,
            self.ttl1,
            self.ttl2,
            self.ttl3,
            self.ttl4,
        )

        index = 11

        for value in analog_channels:
            value &= 0x0FFF
            payload[index] = (value >> 8) & 0x0F
            payload[index + 1] = value & 0xFF
            index += 2

        #
        # Checksum
        #
        checksum_data = command_number + bytes(payload)
        checksum = self.calculate_checksum(checksum_data)

        packet_bytes: bytes = stx + command_number + bytes(payload) + checksum + etx

        return packet_bytes