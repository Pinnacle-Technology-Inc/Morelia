from Morelia.packet import PodPacket

class DataPacket(PodPacket):
    """
    The parent class of all data packets. Purely used for strengthening type safety.
    """
    def __init__(self, raw_packet: bytes, min_length: int) -> None:
        super().__init__(raw_packet, min_length)
