from Morelia.packet import PodPacket

class DataPacket(PodPacket):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
