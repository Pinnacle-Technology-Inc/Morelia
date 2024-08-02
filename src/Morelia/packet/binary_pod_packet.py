from Morelia.packet import PodPacket

class BinaryPodPacket(PodPacket):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
