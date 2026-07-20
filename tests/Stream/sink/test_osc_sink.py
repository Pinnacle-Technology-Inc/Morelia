import threading
import pytest

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer

from Morelia.Stream.sink.osc_sink import OSCSink
from Morelia.Stream.data_flow import DataFlow

class OSCListener:
    def __init__(self, address, host="127.0.0.1", port=9000):
        self._address = address

        self._dispatcher = Dispatcher()
        self._dispatcher.map(address, self._worker)

        self._server = BlockingOSCUDPServer(
            (host, port),
            self._dispatcher
        )

        self._packets = []

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True
        )

    def start(self):
        self._thread.start()

    def stop(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()

    def _worker(self, address, *args):
        self._packets.append(args)

    def get_packets(self):
        return list(self._packets)

@pytest.fixture(scope='function', autouse=True)
def osc_listener():
    listener = OSCListener(address="/test", port=9000)
    listener.start()

    yield listener

    listener.stop()

def test_pod8274D_stream_osc(osc_listener):
    from tests.mocks.device.pod_8274D.MockPodDevice_8274D import MockPod8274D

    # Static variables
    SAMPLE_RATE = 1024
    DURATION_SECONDS = 5

    # Create mock pod 8274D obj
    pod = MockPod8274D(
        device_serial_number='MOCK1',
        sample_rate=SAMPLE_RATE,
    )

    # Create osc sink.
    osc_sink = OSCSink(
        port=9000,
        pod=pod,
        address='/test',
        host="127.0.0.1"
        )

    # create a list of tuples for the pod/sink mappings
    mapping = [(pod, [osc_sink])]

    # create a new DataFlow object using the previous mapping
    flowgraph = DataFlow(mapping)

    flowgraph.collect_for_seconds(DURATION_SECONDS)

    check_osc(
        osc_packets_list=osc_listener.get_packets(),
        seconds=DURATION_SECONDS,
        sample_rate=SAMPLE_RATE,
        samples_per_packet=pod.SAMPLES_PER_PACKET,
    )

def test_pod8401HR_stream_osc(osc_listener):
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

    # Create osc sink.
    osc_sink = OSCSink(
        port=9000,
        pod=pod,
        address='/test',
        host="127.0.0.1"
        )

    # create a list of tuples for the pod/sink mappings
    mapping = [(pod, [osc_sink])]

    # create a new DataFlow object using the previous mapping
    flowgraph = DataFlow(mapping)

    flowgraph.collect_for_seconds(DURATION_SECONDS)

    check_osc(
        osc_packets_list=osc_listener.get_packets(),
        seconds=DURATION_SECONDS,
        sample_rate=SAMPLE_RATE,
    )

def test_pod8206HR_stream_osc(osc_listener):
    from tests.mocks.device.pod_8206HR.MockPodDevice_8206HR import MockPod8206HR

    # Static variables
    SAMPLE_RATE = 2_000
    DURATION_SECONDS = 5

    # Create mock pod 8274D obj
    pod = MockPod8206HR(
        preamp_gain=10,
        sample_rate=SAMPLE_RATE,
    )

    # Create osc sink.
    osc_sink = OSCSink(
        port=9000,
        pod=pod,
        address="/test",
        host="127.0.0.1"
        )

    # create a list of tuples for the pod/sink mappings
    mapping = [(pod, [osc_sink])]

    # create a new DataFlow object using the previous mapping
    flowgraph = DataFlow(mapping)

    flowgraph.collect_for_seconds(DURATION_SECONDS)

    check_osc(
        osc_packets_list=osc_listener.get_packets(),
        seconds=DURATION_SECONDS,
        sample_rate=SAMPLE_RATE,
    )

def check_osc(osc_packets_list, seconds, sample_rate, samples_per_packet=1):
    expected_sampels = int((seconds * sample_rate) / samples_per_packet)
    actual_packets = len(osc_packets_list)

    if expected_sampels <= 0:
        raise ValueError("(seconds * sample_rate) / samples_per_packet) must be > 0")

    missing_packets = max(expected_sampels - actual_packets, 0)

    missing_percent = (missing_packets / expected_sampels) * 100

    assert missing_percent <= 2, (
        f"Expected {expected_sampels} packets, got {actual_packets} packets."
    )
