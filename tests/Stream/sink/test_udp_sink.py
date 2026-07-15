import threading
import socket
import struct
import pytest

from Morelia.Stream.sink.udp_sink import UDPSink
from Morelia.Stream.data_flow import DataFlow

class UDPListener:
    def __init__(self, host="0.0.0.0", port=9000):
        self.host = host
        self.port = port

        self.packets = []

        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._worker,
                daemon=True,
            )
            self._thread.start()

    def stop(self):
        self._stop.set()

        if self._thread:
            self._thread.join(timeout=1)

    def _worker(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.5)
        sock.bind((self.host, self.port))

        try:
            while not self._stop.is_set():
                try:
                    data, addr = sock.recvfrom(4096)
                except socket.timeout:
                    continue

                n = len(data)

                if n == 20:
                    ts, ch0, ch1, ch2 = struct.unpack("<Qfff", data)
                    self.packets.append({
                        "device": "8206HR",
                        "timestamp": ts,
                        "channels": (ch0, ch1, ch2),
                    })

                elif n == 24:
                    ts, ch0, ch1, ch2, ch3 = struct.unpack("<Qffff", data)
                    self.packets.append({
                        "device": "8401HR",
                        "timestamp": ts,
                        "channels": (ch0, ch1, ch2, ch3),
                    })

                elif n == 490:
                    ts, n_samples = struct.unpack("<QH", data[:10])

                    offset = 10
                    samples = []

                    for _ in range(n_samples):
                        samples.append(struct.unpack("<fff", data[offset:offset + 12]))
                        offset += 12

                    self.packets.append({
                        "device": "8274D",
                        "timestamp": ts,
                        "samples": samples,
                    })

        finally:
            sock.close()

@pytest.fixture
def udp_listener():
    listener = UDPListener(port=9000)
    listener.start()

    yield listener

    listener.stop()

def test_pod8274D_stream_udp(udp_listener):
    from tests.mocks.device.pod_8274D.MockPodDevice_8274D import MockPod8274D

    # Static variables
    SAMPLE_RATE = 1024
    DURATION_SECONDS = 5

    # Create mock pod 8274D obj
    pod = MockPod8274D(
        device_serial_number='MOCK1',
        sample_rate=SAMPLE_RATE,
    )

    # Create udp sink.
    udp_sink = UDPSink(
        port=9000,
        pod=pod,
        host="127.0.0.1"
        )

    # create a list of tuples for the pod/sink mappings
    mapping = [(pod, [udp_sink])]

    # create a new DataFlow object using the previous mapping
    flowgraph = DataFlow(mapping)

    flowgraph.collect_for_seconds(DURATION_SECONDS)

    expected_sampels, actual_packets, missing_percent = check_udp(
        udp_packets_list=udp_listener.packets,
        seconds=DURATION_SECONDS,
        sample_rate=SAMPLE_RATE,
        samples_per_packet=pod.SAMPLES_PER_PACKET,
    )
    
    assert missing_percent <= 2, (
        f"Expected {expected_sampels} packets, got {actual_packets} packets."
    )

def test_pod8401HR_stream_udp(udp_listener):
    from tests.mocks.device.pod_8401HR.MockPodDevice_8401HR import MockPod8401HR
    from Morelia.Devices import Preamp
    from Morelia.packet import PrimaryChannelMode, SecondaryChannelMode

    # Static variables
    SAMPLE_RATE = 2_000
    DURATION_SECONDS = 5

    # Create mock pod 8274D obj
    # set preamp gain and ss gain for all channels
    preamp_gain = (10,10,10,10)
    ss_gain = (5,5,5,5)

    # set the primary channel modes to EEG/EMG or BIOSENSOR
    primary_channel_modes = (PrimaryChannelMode.EEG_EMG, PrimaryChannelMode.EEG_EMG, PrimaryChannelMode.EEG_EMG, PrimaryChannelMode.EEG_EMG)

    # set the secondary channel modes to DIGITAL or ANALOG
    secondary_channel_modes =  (SecondaryChannelMode.DIGITAL, SecondaryChannelMode.DIGITAL, SecondaryChannelMode.DIGITAL, SecondaryChannelMode.DIGITAL, SecondaryChannelMode.DIGITAL, SecondaryChannelMode.DIGITAL)

    # create a new 8401HR pod device from the Linux port ttyUSB0, and with the initialized values above
    pod = MockPod8401HR(
                preamp = Preamp.Preamp8406_SE4,
                primary_channel_modes = primary_channel_modes,
                secondary_channel_modes = secondary_channel_modes,
                ss_gain = ss_gain, 
                preamp_gain = preamp_gain,
                )
    
    pod.sample_rate = SAMPLE_RATE

    # Create udp sink.
    udp_sink = UDPSink(
        port=9000,
        pod=pod,
        host="127.0.0.1"
        )

    # create a list of tuples for the pod/sink mappings
    mapping = [(pod, [udp_sink])]

    # create a new DataFlow object using the previous mapping
    flowgraph = DataFlow(mapping)

    flowgraph.collect_for_seconds(DURATION_SECONDS)

    expected_sampels, actual_packets, missing_percent = check_udp(
        udp_packets_list=udp_listener.packets,
        seconds=DURATION_SECONDS,
        sample_rate=SAMPLE_RATE,
    )
    
    assert missing_percent <= 2, (
        f"Expected {expected_sampels} packets, got {actual_packets} packets."
    )

def test_pod8206HR_stream_udp(udp_listener):
    from tests.mocks.device.pod_8206HR.MockPodDevice_8206HR import MockPod8206HR

    # Static variables
    SAMPLE_RATE = 2_000
    DURATION_SECONDS = 5

    # Create mock pod 8274D obj
    pod = MockPod8206HR(
        preamp_gain=10,
        sample_rate=SAMPLE_RATE,
    )

    # Create udp sink.
    udp_sink = UDPSink(
        port=9000,
        pod=pod,
        host="127.0.0.1"
        )

    # create a list of tuples for the pod/sink mappings
    mapping = [(pod, [udp_sink])]

    # create a new DataFlow object using the previous mapping
    flowgraph = DataFlow(mapping)

    flowgraph.collect_for_seconds(DURATION_SECONDS)

    expected_sampels, actual_packets, missing_percent = check_udp(
        udp_packets_list=udp_listener.packets,
        seconds=DURATION_SECONDS,
        sample_rate=SAMPLE_RATE,
    )
    
    assert missing_percent <= 2, (
        f"Expected {expected_sampels} packets, got {actual_packets} packets."
    )

def check_udp(udp_packets_list, seconds, sample_rate, samples_per_packet=1):
    expected_sampels = int((seconds * sample_rate) / samples_per_packet)
    actual_packets = len(udp_packets_list) - 1

    if expected_sampels <= 0:
        raise ValueError("(seconds * sample_rate) / samples_per_packet) must be > 0")

    missing_packets = max(expected_sampels - actual_packets, 0)

    missing_percent = (missing_packets / expected_sampels) * 100

    return (expected_sampels, actual_packets, missing_percent)
