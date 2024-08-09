from Morelia.packet import PodPacket

class DataPacket(PodPacket):
    def __init__(self, raw_packet: bytes, min_length: int) -> None:
        super().__init__(raw_packet, min_length)
