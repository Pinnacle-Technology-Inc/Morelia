from pathlib import Path
import shutil
import time
import pytest

from multiprocessing import Process, Queue

from pvfs_tools.Core.pvfs_data_file import PvfsDataFile

from Morelia.Stream.sink.pvfs_sink import PvfsSink
from Morelia.Stream.data_flow import DataFlow

from tests.helpers.pvfs_utlis import count_samples_worker

"""
PVFS files are analyzed in a separate process instead of the main pytest
process. On Windows, the underlying ``pvfs_tools`` library can retain file
handles after ``close()``, preventing temporary files from being deleted during
fixture teardown. Running the validation in a short-lived child process ensures
all handles are released when the process exits.
"""

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

def test_pod8274D_stream_pvfs(temp_dir):
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
    file_path = temp_dir / "8274D_mock_data.pvfs"

    # Create sink.
    pvfs_sink = PvfsSink(str(file_path), pod)

    # List that defines how sources map to sink.
    mapping = [ (pod, [pvfs_sink]) ]

    # Create the flowgraph.
    flowgraph = DataFlow(mapping)

    # Stream data for a defined time period.
    flowgraph.collect_for_seconds(duration_sec=DURATION_SECONDS)

    check_pvfs_file(
        pvfs_path=file_path,
        seconds=DURATION_SECONDS,
        sample_rate=SAMPLE_RATE,
    )

def test_pod8401HR_stream_pvfs(temp_dir):
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
    file_path = temp_dir / "8401HR_mock_data.pvfs"

    # Create sink.
    pvfs_sink = PvfsSink(str(file_path), pod)

    # List that defines how sources map to sink.
    mapping = [ (pod, [pvfs_sink]) ]

    # Create the flowgraph.
    flowgraph = DataFlow(mapping)

    # Stream data for a defined time period.
    flowgraph.collect_for_seconds(duration_sec=DURATION_SECONDS)

    check_pvfs_file(
        pvfs_path=file_path,
        seconds=DURATION_SECONDS,
        sample_rate=SAMPLE_RATE,
    )

def test_pod8206HR_stream_pvfs(temp_dir):
    from tests.mocks.device.pod_8206HR.MockPodDevice_8206HR import MockPod8206HR

    # Static variables
    SAMPLE_RATE = 2_000
    DURATION_SECONDS = 5

    # Create mock pod 8274D obj
    pod = MockPod8206HR(
        preamp_gain=10,
        sample_rate=SAMPLE_RATE,
    )

    # Set temp file
    file_path = temp_dir / "8206HR_mock_data.pvfs"

    # Create sink.
    pvfs_sink = PvfsSink(str(file_path), pod)

    # List that defines how sources map to sink.
    mapping = [ (pod, [pvfs_sink]) ]

    # Create the flowgraph.
    flowgraph = DataFlow(mapping)

    # Stream data for a defined time period.
    flowgraph.collect_for_seconds(duration_sec=DURATION_SECONDS)

    check_pvfs_file(
        pvfs_path=file_path,
        seconds=DURATION_SECONDS,
        sample_rate=SAMPLE_RATE,
    )

def check_pvfs_file(pvfs_path, seconds, sample_rate):
    """
    Verify a PVFS recording contains the expected number of samples.
    """
    assert pvfs_path.exists(), f"File was never found: {pvfs_path}"

    expected_samples = int(seconds * sample_rate)

    if expected_samples <= 0:
        raise ValueError("seconds * sample_rate must be > 0")

    actual_samples = count_samples(pvfs_path)

    missing_samples = max(expected_samples - actual_samples, 0)
    missing_percent = (missing_samples / expected_samples) * 100

    assert missing_percent <= 2, (
        f"Expected {expected_samples} samples, got {actual_samples} "
        f"({missing_percent:.2f}% missing)."
    )

def count_samples(pvfs_path):
    q = Queue()

    p = Process(
        target=count_samples_worker,
        args=(pvfs_path, q)
    )

    p.start()

    try:
        result = q.get(timeout=10)
    except Exception:
        p.terminate()
        p.join()
        raise RuntimeError(
            "PVFS sample counting worker hung or crashed"
        )

    p.join()

    if p.exitcode != 0:
        raise RuntimeError(
            f"PVFS worker failed with exit code {p.exitcode}"
        )

    if isinstance(result, Exception):
        raise result

    return result

# def _count_samples_worker(pvfs_path, queue):
#     pvfs = PvfsDataFile()

#     if not pvfs.open(str(pvfs_path)):
#         queue.put(RuntimeError(f"Could not open PVFS file: {pvfs_path}"))
#         return

#     try:
#         channels = list(pvfs._indexed_data_files.values())

#         if not channels:
#             queue.put(ValueError("PVFS contains no indexed data channels."))
#             return

#         lengths = []

#         for channel in channels:
#             start = channel.get_start_time()
#             end = channel.get_end_time()
#             _, samples = channel.get_data(start, end)
#             lengths.append(len(samples))

#         queue.put(lengths[0])

#     finally:
#         pvfs.close()


# def count_samples(pvfs_path):
#     q = Queue()

#     p = Process(target=_count_samples_worker, args=(pvfs_path, q))
#     p.start()

#     result = q.get()

#     p.join()

#     if p.is_alive():
#         p.terminate()
#         p.join()

#     p.close()

#     if isinstance(result, Exception):
#         raise result

#     return result

