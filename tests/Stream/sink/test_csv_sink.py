from pathlib import Path
import shutil
import csv
import pytest

from Morelia.Stream.sink.csv_sink import CSVSink
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

def test_pod8274D_stream_csv(temp_dir):
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
    file_path = temp_dir / "8274D_mock_data.csv"

    # Create sink.
    csv_sink = CSVSink(str(file_path), pod)

    # List that defines how sources map to sink.
    mapping = [ (pod, [csv_sink]) ]

    # Create the flowgraph.
    flowgraph = DataFlow(mapping)

    # Stream data for a defined time period.
    flowgraph.collect_for_seconds(duration_sec=DURATION_SECONDS)
    
    assert file_path.exists(), f"File was never found: {file_path}"

    expected_rows, actual_rows, missing_percent = check_csv_file(
        csv_path=file_path,
        seconds=DURATION_SECONDS,
        sample_rate=SAMPLE_RATE,
        skip_header=True
    )

    assert has_csv_header(file_path), (
        f"CSV does not appear to contain a header row: {file_path}"
    )
    assert missing_percent <= 2, (
        f"Expected {expected_rows} rows, got {actual_rows} rows."
    )

def test_pod8401HR_stream_csv(temp_dir):
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
    file_path = temp_dir / "8401HR_mock_data.csv"

    # Create sink.
    csv_sink = CSVSink(str(file_path), pod)

    # List that defines how sources map to sink.
    mapping = [ (pod, [csv_sink]) ]

    # Create the flowgraph.
    flowgraph = DataFlow(mapping)

    # Stream data for a defined time period.
    flowgraph.collect_for_seconds(duration_sec=DURATION_SECONDS)
    
    assert file_path.exists(), f"File was never found: {file_path}"

    expected, actual, missing_percent = check_csv_file(
        csv_path=file_path,
        seconds=DURATION_SECONDS,
        sample_rate=SAMPLE_RATE,
    )

    assert has_csv_header(file_path), (
        f"CSV does not appear to contain a header row: {file_path}"
    )
    assert missing_percent <= 2, (
        f"Expected {expected} average samples per channel, got {actual}."
    )

def test_pod8206HR_stream_csv(temp_dir):
    from tests.mocks.device.pod_8206HR.MockPodDevice_8206HR import MockPod8206HR

    # Static variables
    SAMPLE_RATE = 2_000
    DURATION_SECONDS = 5

    # Create mock pod 8274D obj
    pod = MockPod8206HR(
        preamp_gain=10
    )

    # Set temp file
    file_path = temp_dir / "8206HR_mock_data.csv"

    # Create sink.
    csv_sink = CSVSink(str(file_path), pod)

    # List that defines how sources map to sink.
    mapping = [ (pod, [csv_sink]) ]

    # Create the flowgraph.
    flowgraph = DataFlow(mapping)

    # Stream data for a defined time period.
    flowgraph.collect_for_seconds(duration_sec=DURATION_SECONDS)
    
    assert file_path.exists(), f"File was never found: {file_path}"

    expected_rows, actual_rows, missing_percent = check_csv_file(
        csv_path=file_path,
        seconds=DURATION_SECONDS,
        sample_rate=SAMPLE_RATE,
        skip_header=True
    )

    assert has_csv_header(file_path), (
        f"CSV does not appear to contain a header row: {file_path}"
    )
    assert missing_percent <= 2, (
        f"Expected {expected_rows} rows, got {actual_rows} rows."
    )

def count_rows(csv_path, skip_header=True):
    """
    Count the number of data rows in a CSV file.

    Parameters
    ----------
    csv_path : str or Path
        Path to the CSV file.
    skip_header : bool, optional
        If True (default), the first row is treated as a header and is not
        included in the count.

    Returns
    -------
    int
        Number of rows in the CSV file, excluding the header if
        ``skip_header`` is True.
    """
    with open(csv_path, "r", newline="") as f:
        reader = csv.reader(f)

        count = 0
        for i, _ in enumerate(reader):
            if skip_header and i == 0:
                continue
            count += 1

        return count

def check_csv_file(csv_path, seconds, sample_rate, skip_header=True):
    """
    Calculate the percentage of missing samples in a recorded CSV file.

    The expected number of samples is computed as::

        expected_rows = seconds * sample_rate

    The actual number of samples is determined by counting the rows in the
    CSV file. If the file contains fewer samples than expected, the number
    and percentage of missing samples are returned.

    Parameters
    ----------
    csv_path : str or Path
        Path to the CSV file.
    seconds : float
        Expected recording duration in seconds.
    sample_rate : int
        Expected sampling rate in samples per second (Hz).
    skip_header : bool, optional
        If True (default), the first row of the CSV is treated as a header
        and excluded from the row count.

    Returns
    -------
    tuple[int, int, int, float]
        A tuple containing:

        - expected_rows: Expected number of samples.
        - actual_rows: Number of samples found in the CSV.
        - missing_rows: Number of missing samples (never negative).

    Raises
    ------
    ValueError
        If ``seconds * sample_rate`` is less than or equal to zero.
    """
    expected_rows = int(seconds * sample_rate)
    actual_rows = count_rows(csv_path, skip_header=skip_header)

    if expected_rows <= 0:
        raise ValueError("seconds * sample_rate must be > 0")

    missing_rows = max(expected_rows - actual_rows, 0)

    missing_percent = (missing_rows / expected_rows) * 100

    return (expected_rows, actual_rows, missing_percent)

def has_csv_header(csv_path):
    """
    Check whether a CSV file contains a header row rather than data.

    Returns
    -------
    bool
        True if the first row contains at least one non-numeric value,
        otherwise False.
    """
    with open(csv_path, "r", newline="") as f:
        header = next(csv.reader(f), None)

    if not header:
        return False

    for value in header:
        try:
            float(value)
        except ValueError:
            return True

    return False