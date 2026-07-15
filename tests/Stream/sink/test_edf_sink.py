from pathlib import Path
import shutil
import pyedflib
import pytest

from Morelia.Stream.sink.edf_sink import EDFSink
from Morelia.Stream.data_flow import DataFlow

@pytest.fixture(scope="session", autouse=True)
def temp_dir():
    """
    Creates a temporary test folder next to this file before any tests run
    and removes it after the test session finishes.
    """

    script_dir = Path(__file__).resolve().parent
    temp_dir = script_dir / "temp"

    # Remove any leftover folder from a previous run
    if temp_dir.exists():
        shutil.rmtree(temp_dir)

    temp_dir.mkdir(parents=True)

    yield temp_dir

    # Cleanup
    if temp_dir.exists():
        shutil.rmtree(temp_dir)

def test_pod8274D_stream_edf(temp_dir):
    from tests.mocks.device.pod_8274D.MockPodDevice_8274D import MockPod8274D

    # Static variables
    SAMPLE_RATE = 1024
    DURATION_SECONDS = 5

    # Create mock pod 8274D obj
    pod = MockPod8274D(
        device_serial_number='MOCK1',
        sample_rate=SAMPLE_RATE,
    )

    # Set temp file
    file_path = temp_dir / "8274D_mock_data.edf"

    # Create sink.
    edf_sink = EDFSink(str(file_path), pod)

    # List that defines how sources map to sink.
    mapping = [ (pod, [edf_sink]) ]

    # Create the flowgraph.
    flowgraph = DataFlow(mapping)

    # Stream data for a defined time period.
    flowgraph.collect_for_seconds(duration_sec=DURATION_SECONDS)
    
    assert file_path.exists(), f"File was never found: {file_path}"

    expected, actual, missing_percent = check_edf_file(
        edf_path=file_path,
        seconds=DURATION_SECONDS,
        sample_rate=SAMPLE_RATE,
    )

    assert missing_percent <= 2, (
        f"Expected {expected} average samples per channel, got {actual}."
    )

def test_pod8401HR_stream_edf(temp_dir):
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
    
    # Set temp file
    file_path = temp_dir / "8401HR_mock_data.edf"

    # Create sink.
    edf_sink = EDFSink(str(file_path), pod)

    # List that defines how sources map to sink.
    mapping = [ (pod, [edf_sink]) ]

    # Create the flowgraph.
    flowgraph = DataFlow(mapping)

    # Stream data for a defined time period.
    flowgraph.collect_for_seconds(duration_sec=DURATION_SECONDS)
    
    assert file_path.exists(), f"File was never found: {file_path}"

    expected, actual, missing_percent = check_edf_file(
        edf_path=file_path,
        seconds=DURATION_SECONDS,
        sample_rate=SAMPLE_RATE,
    )

    max_missing_samples = SAMPLE_RATE + int(expected * 0.02)
    missing_samples = max(expected - actual, 0)

    # pyedflib writes complete EDF records only. If streaming stops before the
    # final record is completely filled, the library discards that record.
    # Therefore, up to one record (sample_rate samples) may be absent.
    assert missing_samples <= max_missing_samples, (
        f"Missing {missing_samples}/{expected} samples "
        f"({missing_samples / expected * 100:.2f}%). "
        f"Allowed {max_missing_samples} samples."
    )

def test_pod8206HR_stream_edf(temp_dir):
    from tests.mocks.device.pod_8206HR.MockPodDevice_8206HR import MockPod8206HR

    # Static variables
    SAMPLE_RATE = 2_000
    DURATION_SECONDS = 5

    # Create mock pod 8274D obj
    pod = MockPod8206HR(
        preamp_gain=10,
        sample_rate=SAMPLE_RATE
    )

    # Set temp file
    file_path = temp_dir / "8401HR_mock_data.edf"

    # Create sink.
    edf_sink = EDFSink(str(file_path), pod)

    # List that defines how sources map to sink.
    mapping = [ (pod, [edf_sink]) ]

    # Create the flowgraph.
    flowgraph = DataFlow(mapping)

    # Stream data for a defined time period.
    flowgraph.collect_for_seconds(duration_sec=DURATION_SECONDS)
    
    assert file_path.exists(), f"File was never found: {file_path}"

    expected, actual, missing_percent = check_edf_file(
        edf_path=file_path,
        seconds=DURATION_SECONDS,
        sample_rate=SAMPLE_RATE,
    )

    max_missing_samples = SAMPLE_RATE + int(expected * 0.02)
    missing_samples = max(expected - actual, 0)

    # pyedflib writes complete EDF records only. If streaming stops before the
    # final record is completely filled, the library discards that record.
    # Therefore, up to one record (sample_rate samples) may be absent.
    assert missing_samples <= max_missing_samples, (
        f"Missing {missing_samples}/{expected} samples "
        f"({missing_samples / expected * 100:.2f}%). "
        f"Allowed {max_missing_samples} samples."
    )

# Helper Functions
def count_samples(edf_path):
    """
    Count the average number of samples per channel in an EDF file.

    Parameters
    ----------
    edf_path : str or Path
        Path to the EDF file.

    Returns
    -------
    int
        Average number of samples recorded per channel.
    """
    f = pyedflib.EdfReader(str(edf_path))

    try:
        samples_per_signal = f.getNSamples()
        return int(sum(samples_per_signal) / f.signals_in_file)
    finally:
        f.close()


def check_edf_file(edf_path, seconds, sample_rate):
    """
    Calculate the number of missing samples in an EDF recording.

    The expected number of samples is computed as::

        expected_samples = seconds * sample_rate

    The actual number of samples is the average number of samples recorded
    across all channels.

    Parameters
    ----------
    edf_path : str or Path
        Path to the EDF file.
    seconds : float
        Expected recording duration in seconds.
    sample_rate : int
        Expected sampling rate in samples per second (Hz).

    Returns
    -------
    tuple[int, int, int]
        A tuple containing:

        - expected_samples: Expected number of samples per channel.
        - actual_samples: Average number of samples per channel.
        - missing_samples: Number of missing samples (never negative).

    Raises
    ------
    ValueError
        If ``seconds * sample_rate`` is less than or equal to zero.
    """
    expected_samples = int(seconds * sample_rate)
    actual_samples = count_samples(edf_path)

    if expected_samples <= 0:
        raise ValueError("seconds * sample_rate must be > 0")

    missing_samples = max(expected_samples - actual_samples, 0)

    missing_percent = (missing_samples / expected_samples) * 100

    return (expected_samples, actual_samples, missing_percent)