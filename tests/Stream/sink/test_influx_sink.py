import pytest

from multiprocessing import Manager

from Morelia.Stream.data_flow import DataFlow

from tests.mocks.sink.influx_sink.MockInfluxSink import MockInfluxSink

@pytest.fixture
def shared_records():
    '''
    DataFlow runs in a separate process, so a multiprocessing.Manager is used
    to create a list that can be shared between the worker process and this test.
    '''
    # Setup shared list
    manager = Manager()
    shared_records = manager.list()

    yield shared_records

    manager.shutdown()

def test_pod8274D_stream_influx_sink(shared_records):
    from tests.mocks.device.pod_8274D.MockPodDevice_8274D import MockPod8274D

    # Static variables
    SAMPLE_RATE = 1024
    DURATION_SECONDS = 5

    # Create mock pod device
    pod = MockPod8274D(
        device_serial_number="MOCK1",
        sample_rate=SAMPLE_RATE,
    )

    # Create influx sink.
    influx_sink = MockInfluxSink(
        pod=pod,
        shared_records=shared_records,
        )

    # List that defines how sources map to sinks.
    mapping = [ (pod, [influx_sink]) ]

    # Create the flowgraph.
    flowgraph = DataFlow(mapping)

    # Collect data
    flowgraph.collect_for_seconds(DURATION_SECONDS)

    # Run test
    count_samples(
        shared_records=shared_records,
        sample_rate=SAMPLE_RATE,
        duration_seconds=DURATION_SECONDS,
        samples_per_packet=pod.SAMPLES_PER_PACKET,
    )

def test_pod8401HR_stream_edf(shared_records):
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
    
    # Set sample rate
    pod.sample_rate = SAMPLE_RATE
    
    # Create influx sink.
    influx_sink = MockInfluxSink(
        pod=pod,
        shared_records=shared_records,
        )

    # List that defines how sources map to sinks.
    mapping = [ (pod, [influx_sink]) ]

    # Create the flowgraph.
    flowgraph = DataFlow(mapping)

    # Collect data
    flowgraph.collect_for_seconds(DURATION_SECONDS)

    # Run test
    count_samples(
        shared_records=shared_records,
        sample_rate=SAMPLE_RATE,
        duration_seconds=DURATION_SECONDS,
    )

def test_pod8206HR_stream_edf(shared_records):
    from tests.mocks.device.pod_8206HR.MockPodDevice_8206HR import MockPod8206HR

    # Static variables
    SAMPLE_RATE = 2_000
    DURATION_SECONDS = 5

    # Create mock pod 8274D obj
    pod = MockPod8206HR(
        preamp_gain=10,
        sample_rate=SAMPLE_RATE
    )

    # Create influx sink.
    influx_sink = MockInfluxSink(
        pod=pod,
        shared_records=shared_records,
        )

    # List that defines how sources map to sinks.
    mapping = [ (pod, [influx_sink]) ]

    # Create the flowgraph.
    flowgraph = DataFlow(mapping)

    # Collect data
    flowgraph.collect_for_seconds(DURATION_SECONDS)

    # Run test
    count_samples(
        shared_records=shared_records,
        sample_rate=SAMPLE_RATE,
        duration_seconds=DURATION_SECONDS,
    )

# Helper Function
def count_samples(shared_records, sample_rate, duration_seconds, samples_per_packet=1):
    samples = len(shared_records) * samples_per_packet
    expected = sample_rate * duration_seconds

    missing = expected - samples
    missing_percent = missing / expected * 100

    assert missing_percent <= 2, (
        f"Expected {expected} average samples per channel, got {samples}."
    )