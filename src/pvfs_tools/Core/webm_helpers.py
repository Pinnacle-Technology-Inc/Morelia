#webm helpers
import av
from fractions import Fraction

class WebMWriter:
    def __init__(self, output_path: str, frame_rate: float, width: int, height: int):
        from fractions import Fraction
        import av

        self.container = av.open(output_path, mode='w', format='webm')
        rate = Fraction(frame_rate).limit_denominator(1000000)
        self.stream = self.container.add_stream("vp8", rate=rate)
        self.stream.rate = rate
        self.stream.time_base = Fraction(rate.denominator, rate.numerator)

        self.stream.width = width
        self.stream.height = height

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def write_frame(self, frame_bytes: bytes, is_keyframe: bool, frame_index: int, frame_rate: float):
        if frame_rate <= 0:
            frame_rate = 30.
        packet = av.packet.Packet(frame_bytes)
        packet.stream = self.stream
        timestamp_sec = frame_index/frame_rate
        packet.pts = int(timestamp_sec * 1000)    # ms, matches 1/1000 time_base
        packet.dts = packet.pts
        packet.duration = int(1000 / frame_rate)  # e.g., 50 ms for 20 fps
        packet.is_keyframe = is_keyframe

        self.container.mux(packet)

    def close(self):
        if self.container:
            self.container.close()
            self.container = None