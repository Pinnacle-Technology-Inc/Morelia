#webm helpers
import av
from fractions import Fraction

class WebMWriter:
    def __init__(self, output_path: str, frame_rate: float, width: int, height: int):
        from fractions import Fraction
        import av

        self.container = av.open(output_path, mode='w', format='webm')
        self.stream = self.container.add_stream("vp8", rate=Fraction(frame_rate).limit_denominator())
        self.stream.width = width
        self.stream.height = height

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def write_frame(self, frame_data: bytes, is_keyframe: bool = False):
        packet = av.Packet(frame_data)
        packet.is_keyframe = is_keyframe
        self.container.mux_one(packet)

    def close(self):
        if self.container:
            self.container.close()
            self.container = None