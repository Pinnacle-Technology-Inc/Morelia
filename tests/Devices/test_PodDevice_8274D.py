"""
Unit tests for the Pod8274D device.

These tests verify the behavior of the 8274D acquisition device,
including:

- Device discovery and connection.
- Automatic connection during initialization.
- Sample rate configuration and validation.
- Device information queries.
- Streaming data packet generation.
- Context manager behavior and cleanup.

The tests use MockPod8274D to validate device behavior without requiring
physical hardware.
"""

import pytest

from Morelia.packet.data import DataPacket8274D
from tests.mocks.device.pod_8274D.MockPodDevice_8274D import MockPod8274D

DEVICE_SERIAL_NUMBER = "MOCK1"

@pytest.fixture(scope='function')
def pod():
    """
    Create a MockPod8274D instance shared by tests that do not
    modify connection state.
    """
    pod = MockPod8274D(
        device_serial_number=DEVICE_SERIAL_NUMBER,
        sample_rate=1024,
        )

    yield pod

def test_connect_to_existing_device():
    pod = MockPod8274D()
    
    pod.connect_to_device(
        device_serial_number=DEVICE_SERIAL_NUMBER
        )

    # Connected
    assert pod._connected is True
    assert pod._connection_slot == 0

    # Scan was disabled after connecting
    assert pod._scan_enabled is False

    # Gains were updated from the model number
    assert pod._primary_gain == 100
    assert pod._secondary_gain == 26

def test_connect_to_device_on_init_success():
    pod = MockPod8274D(
        device_serial_number=DEVICE_SERIAL_NUMBER,
        sample_rate=1024,
        )

    # Connected
    assert pod._connected is True
    assert pod._connection_slot == 0

    # Scan was disabled after connecting
    assert pod._scan_enabled is False

    # Gains were updated from the model number
    assert pod._primary_gain == 100
    assert pod._secondary_gain == 26

    # Sample rate from init of obj
    assert pod._sample_rate == 1024
    assert pod.write_read('GET SAMPLE RATE') == 1024

def test_connect_to_device_on_init_fail():
    with pytest.raises(TimeoutError):
        pod = MockPod8274D(
            device_serial_number='MOCK4',
            sample_rate=1024,
            scan_timeout_sec=0.1,
            )

def test_sample_rate_set_and_get_success(pod):
    for sample_rate in pod._SAMPLE_RATE_INDEX.values():
        pod.sample_rate = sample_rate

        assert pod.sample_rate == sample_rate

def test_set_sample_rate_fail_invalid_sample_rate(pod):
    original_sample_rate = pod.sample_rate

    with pytest.raises(ValueError):
        pod.sample_rate = 2048
    
    assert pod.sample_rate == original_sample_rate

def test_get_sample_rate_without_initializing():
    pod = MockPod8274D(
        device_serial_number=DEVICE_SERIAL_NUMBER,
        )
    
    assert pod.sample_rate == pod._device_default_sample_rate

def test_connect_by_invalid_device_serial_number_fail():
    with pytest.raises(TypeError):
        pod = MockPod8274D(
            device_serial_number=12345,
            )

def test_get_name_success(pod):
    r = pod.write_read("GET NAME")

    assert r == f'8274-{DEVICE_SERIAL_NUMBER}'


def test_read_pod_packet_streaming_returns_data_packet():
    pod = MockPod8274D(
        device_serial_number=DEVICE_SERIAL_NUMBER,
        sample_rate=1024,
    )

    pod.write_packet("STREAM", 1)
    packet = pod.read_pod_packet_streaming(timeout_sec=0.1)
    packet = pod.read_pod_packet_streaming(timeout_sec=0.1)

    pod.write_packet("STREAM", 0)

    assert isinstance(packet, DataPacket8274D)
    assert len(packet.ch5) == pod.SAMPLES_PER_PACKET
    assert len(packet.ch6) == pod.SAMPLES_PER_PACKET
    assert len(packet.ch7) == pod.SAMPLES_PER_PACKET
    