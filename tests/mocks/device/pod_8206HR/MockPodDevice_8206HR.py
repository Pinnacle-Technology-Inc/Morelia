import threading
import time
import math

from collections import deque

import Morelia.packet.conversion as conv

from Morelia.Commands import CommandSet
from Morelia.packet.pod_packet import PodPacket
from Morelia.packet.control_packet import ControlPacket
from Morelia.packet.data.data_packet_8206hr import DataPacket8206HR
from Morelia.Devices.PodDevice_8206HR import Pod8206HR
from Morelia.packet import ControlPacket, PodPacket

from tests.mocks.packet.MockControlPacket import MockControlPacket
from tests.mocks.port.MockPort import MockPort
from tests.mocks.port.MockQueueManager import MockQueueManager
from tests.mocks.packet.data.MockDataPacket8206HR import MockDataPacket8206HR

_BINARY_CMD_NUM = 180

class MockPod8206HR(Pod8206HR):
    def __init__(self,
                port=None, # port must be in here for when the obj is recreated from get_dict during sink use
                preamp_gain: tuple[int|None]=(None, None, None, None), 
                baudrate:int=9600,
                device_name: str | None = None,
                use_d2xx: bool = False, # Must remain False, name setup manually here
                sample_rate: int = None,
                ):
        
        self._baudrate = baudrate
        self._use_d2xx = use_d2xx

        self._max_sample_rate = 2_000

        self._sample_rate = sample_rate
        
        # Default sample rate for device on boot if not set
        self._device_default_sample_rate = 2_000

        self._port_read_queue = deque()
        
        self._port = MockPort(read_queue=self._port_read_queue)
        self._port_value = "MOCK_PORT"
        
        self.device_plugged_into_usb = True # Simulate device plugged into USB or not
        
        self._device_name: str = device_name if device_name else str(self._port)

        self._manager = MockQueueManager()
        
        self._stream_counter = 0

        self._stream_thread = None
        self._stream_stop = threading.Event()

        self._commands : CommandSet = CommandSet()
        self._init_device(
            preamp_gain=preamp_gain,
            sample_rate=sample_rate,
        )

    # CORE MOCK TRANSPORT
    def write_packet(self, cmd, payload=None) -> None:
        self.device_response(cmd, payload)

    def flush_port(self) -> None:
        self._port_read_queue.clear()

    def _stop_streaming(self) -> None:
        self._stream_stop.set()
        if self._stream_thread is not None:
            self._stream_thread.join(timeout=0.5)
            if not self._stream_thread.is_alive():
                self._stream_thread = None

    def close_port(self) -> None:
        self._stop_streaming()
        super().close_port()

    def read_pod_packet(self, timeout_sec=1.0, validate_checksum=False) -> PodPacket:
        deadline = time.monotonic() + timeout_sec

        while time.monotonic() < deadline:
            if self._port_read_queue:
                raw_packet = self._port_read_queue.popleft()

                packet = PodPacket(raw_packet)
                cmd_num = packet.command_number

                if cmd_num == _BINARY_CMD_NUM:  # Command 181 for binary meaning data packet
                    return DataPacket8206HR(
                        raw_packet=raw_packet,
                        preamp_gain=self._preamp_gain,
                    )
                else:
                    return ControlPacket(
                        decode_from=self._commands,
                        raw_packet=raw_packet
                    )

            time.sleep(0.01)

        raise TimeoutError("No packet received from mock device within timeout")

    def device_response(self, cmd, payload) -> None:
        if not self.device_plugged_into_usb: # Simulate device is not plugged into USB or not responding
            return
        
        # PING
        if cmd == "PING":
            self._port_read_queue.append(
                MockControlPacket(
                    command_number=2,
                ).to_bytes()
            )
            return

        # RESET
        if cmd == "RESET":
            self.flush_port()
            self._port_read_queue.append(
                MockControlPacket(
                    command_number=3,
                ).to_bytes()
            )
            return

        # SAMPLE RATE GET
        if cmd == "GET SAMPLE RATE":
            sample_rate = self._device_default_sample_rate if self._sample_rate is None else self._sample_rate

            self._port_read_queue.append(
                MockControlPacket( # Return sample rate
                    command_number=100,
                    payload=conv.int_to_ascii_bytes(sample_rate, 4),
                ).to_bytes()
            )
            return

        # SAMPLE RATE SET
        if cmd == "SET SAMPLE RATE":
            self._sample_rate = payload[0] # Set mock device's sample rate
            
            self._port_read_queue.append(
                MockControlPacket( # Return procedure complete
                    command_number=101
                ).to_bytes()
            )
            return
        
        if cmd == "STREAM":
            if payload == 0 or payload == 1:
                payload_bytes = conv.int_to_ascii_bytes(payload, 2)
                self._port_read_queue.append(
                    MockControlPacket(
                        command_number=6,
                        payload=payload_bytes,
                    ).to_bytes()
                )

                if payload == 1: # Start streaming
                    if self._stream_thread is None or not self._stream_thread.is_alive():
                        self._stream_stop.clear()
                        self._stream_thread = threading.Thread(
                            target=self._stream_worker,
                            daemon=True,
                        )
                        self._stream_thread.start()

                elif payload == 0: # Stop streaming
                    self._stop_streaming()
        return

    # Sine wave
    def _stream_worker(self):
        last_time = time.perf_counter()
        fractional_samples = 0.0

        frequency = 10.0      # Hz
        amplitude = 500
        offset = 32768

        sample_index = 0

        while not self._stream_stop.is_set():

            now = time.perf_counter()
            elapsed = now - last_time
            last_time = now

            fractional_samples += elapsed * self.sample_rate
            samples = int(fractional_samples)
            fractional_samples -= samples

            for _ in range(samples):
                t = sample_index / self.sample_rate

                theta = 2 * math.pi * frequency * t

                ch0 = int(offset + amplitude * math.sin(theta))
                ch1 = int(offset + amplitude * math.sin(theta + math.pi / 2))
                ch2 = int(offset + amplitude * math.sin(theta + math.pi))

                self._port_read_queue.append(
                    MockDataPacket8206HR(
                        ch0=ch0,
                        ch1=ch1,
                        ch2=ch2,
                        ttl1=0,
                        ttl2=0,
                        ttl3=0,
                        ttl4=0,
                        packet_number=self._stream_counter,
                    ).to_bytes()
                )

                sample_index += 1
                self._stream_counter = (self._stream_counter + 1) & 0xFF

            self._stream_stop.wait(min(0.01, 1 / self.sample_rate))

    def __enter__(self):
        return super().__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.write_packet("STREAM", 0)

        for _ in range(3):
            try:
                self.read_pod_packet(timeout_sec=0.05)
            except TimeoutError:
                break

        return False

    def check_write_queue(self):
        # Mock doesn't use an inter-process write queue.
        return
