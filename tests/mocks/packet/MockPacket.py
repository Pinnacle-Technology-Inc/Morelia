import Morelia.packet.conversion as conv


class MockPacket:
    """
    Base class for mock POD packets.

    Provides shared utilities used by all mock packet generators.
    """

    @staticmethod
    def calculate_checksum(packet_bytes: bytes) -> bytes:
        """
        Calculate the POD checksum.

        The checksum is computed by:
            1. Summing all byte values.
            2. Taking the bitwise NOT.
            3. Keeping the least-significant byte.
            4. Returning it as two ASCII hex characters.

        Parameters
        ----------
        packet_bytes : bytes
            All bytes after STX and before the checksum field.

        Returns
        -------
        bytes
            Two ASCII bytes representing the checksum.
        """
        checksum = (~sum(packet_bytes)) & 0xFF
        return conv.int_to_ascii_bytes(checksum, 2)