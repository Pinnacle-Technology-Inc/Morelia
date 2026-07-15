import time
from collections import deque


class MockPort:
    def __init__(self, read_queue=None):
        self._read_queue = read_queue if read_queue is not None else deque()
        self._buffer = bytearray()

    def close_serial_port(self):
        pass

    def open_serial_port(self):
        pass

    def flush_input(self):
        pass

    def flush_output(self):
        pass

    def read(self, numBytes, timeout_sec=5):
        deadline = time.monotonic() + timeout_sec

        while len(self._buffer) < numBytes:
            if self._read_queue:
                packet = self._read_queue.popleft()

                if not isinstance(packet, (bytes, bytearray)):
                    packet = bytes(packet)

                self._buffer.extend(packet)
            else:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Expected {numBytes} bytes, got {len(self._buffer)}"
                    )
                
                time.sleep(0.001)

        result = bytes(self._buffer[:numBytes])
        del self._buffer[:numBytes]

        return result