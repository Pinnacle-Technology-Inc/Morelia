from multiprocessing import Manager

from Morelia.Stream.sink.buffer_sink import BufferSink
from Morelia.Stream.data_flow import DataFlow

def test_pod8274D_stream_buffer():
    from tests.mocks.device.pod_8274D.MockPodDevice_8274D import MockPod8274D

    # Static variables
    SAMPLE_RATE = 1024
    DURATION_SECONDS = 5

    # Create mock pod 8274D obj
    pod = MockPod8274D(
        device_serial_number='MOCK1',
        sample_rate=SAMPLE_RATE,
    )

    SAMPLES_PER_BATCH = pod.SAMPLES_PER_PACKET

    manager = Manager()
    buffer = manager.list()

    # Create the BufferSink
    buffer_sink = BufferSink(buffer, pod)

    # create mapping
    mapping = [(pod, [buffer_sink])]

    # create DataFlow
    flowgraph = DataFlow(mapping)

    # Collect for time period
    flowgraph.collect_for_seconds(duration_sec=DURATION_SECONDS)
    
    assert buffer, f"Buffer can't be found. May have never been created."

    expected_rows, actual_rows, missing_percent = check_buffer(
        buffer=buffer,
        seconds=DURATION_SECONDS,
        sample_rate=SAMPLE_RATE,
        samples_per_packet=SAMPLES_PER_BATCH,
        skip_header=True
    )

    assert has_buffer_header(buffer), (
        f"buffer does not appear to contain a header row."
    )
    assert missing_percent <= 2, (
        f"Expected {expected_rows} rows, got {actual_rows} rows."
    )

def test_pod8401HR_stream_buffer():
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
    
    manager = Manager()
    buffer = manager.list()

    # Create the BufferSink
    buffer_sink = BufferSink(buffer, pod)

    # create mapping
    mapping = [(pod, [buffer_sink])]

    # create DataFlow
    flowgraph = DataFlow(mapping)

    # Collect for time period
    flowgraph.collect_for_seconds(duration_sec=DURATION_SECONDS)
    
    assert buffer, f"Buffer can't be found. May have never been created."

    expected_rows, actual_rows, missing_percent = check_buffer(
        buffer=buffer,
        seconds=DURATION_SECONDS,
        sample_rate=SAMPLE_RATE,
        skip_header=True
    )

    assert has_buffer_header(buffer), (
        f"buffer does not appear to contain a header row."
    )
    assert missing_percent <= 2, (
        f"Expected {expected_rows} rows, got {actual_rows} rows."
    )

def test_pod8206HR_stream_buffer():
    from tests.mocks.device.pod_8206HR.MockPodDevice_8206HR import MockPod8206HR

    # Static variables
    SAMPLE_RATE = 2_000
    DURATION_SECONDS = 5

    # Create pod mock object
    pod = MockPod8206HR(preamp_gain=10)

    # Set the sample rate.
    pod.sample_rate = SAMPLE_RATE
    
    manager = Manager()
    buffer = manager.list()

    # Create the BufferSink
    buffer_sink = BufferSink(buffer, pod)

    # create mapping
    mapping = [(pod, [buffer_sink])]

    # create DataFlow
    flowgraph = DataFlow(mapping)

    # Collect for time period
    flowgraph.collect_for_seconds(duration_sec=DURATION_SECONDS)
    
    assert buffer, f"Buffer can't be found. May have never been created."

    expected_rows, actual_rows, missing_percent = check_buffer(
        buffer=buffer,
        seconds=DURATION_SECONDS,
        sample_rate=SAMPLE_RATE,
        skip_header=True
    )

    assert has_buffer_header(buffer), (
        f"buffer does not appear to contain a header row."
    )
    assert missing_percent <= 2, (
        f"Expected {expected_rows} rows, got {actual_rows} rows."
    )

def check_buffer(buffer, seconds, sample_rate, samples_per_packet=1, skip_header=True):
    """
    Calculate the number of missing entries in a recorded data buffer.

    The expected number of entries is computed as::

        expected_rows = (seconds * sample_rate) / samples_per_packet

    The actual number of entries is determined by counting the rows in the
    buffer, excluding the header row.

    Parameters
    ----------
    buffer : sequence
        Buffer containing a header row followed by recorded data rows.
    seconds : float
        Expected recording duration in seconds.
    sample_rate : int
        Expected sampling rate in samples per second (Hz).
    samples_per_packet : int, optional
        Number of samples represented by each buffer entry. Defaults to 1.

    Returns
    -------
    tuple[int, int, int]
        A tuple containing:

        - expected_rows: Expected number of buffer entries.
        - actual_rows: Number of data entries found in the buffer.
        - missing_rows: Number of missing entries (never negative).

    Raises
    ------
    ValueError
        If ``(seconds * sample_rate) / samples_per_packet`` is less than or
        equal to zero.
    """
    expected_rows = int((seconds * sample_rate) / samples_per_packet)
    actual_rows = len(buffer) - 1

    if expected_rows <= 0:
        raise ValueError("(seconds * sample_rate) / samples_per_packet) must be > 0")

    missing_rows = max(expected_rows - actual_rows, 0)

    missing_percent = (missing_rows / expected_rows) * 100

    return (expected_rows, actual_rows, missing_percent)

def has_buffer_header(buffer):
    """
    Check whether a buffer contains a header row rather than data.

    The first row is considered a header if it contains at least one
    non-numeric value.

    Parameters
    ----------
    buffer : sequence
        Buffer containing a header row followed by recorded data rows.

    Returns
    -------
    bool
        True if the first row appears to be a header, otherwise False.
    """
    header = buffer[0]

    if not header:
        return False

    for value in header:
        try:
            float(value)
        except ValueError:
            return True

    return False