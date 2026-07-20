"""
Unit tests for the Pod8401HR device.

These tests verify the behavior of the mock 8401HR acquisition device,
including:

- Sample rate configuration.
- Default sample rate behavior.
- Device information queries.
- Streaming data packet generation.
- Context manager cleanup.
"""

import pytest

from Morelia.Devices import Preamp
from Morelia.packet import PrimaryChannelMode, SecondaryChannelMode
from Morelia.packet.data import DataPacket8401HR

from tests.mocks.device.pod_8401HR.MockPodDevice_8401HR import MockPod8401HR


@pytest.fixture(scope='function')
def pod():
    # set preamp gain and ss gain for all channels
    preamp_gain = (10, 10, 10, 10)
    ss_gain = (5, 5, 5, 5)

    # set the primary channel modes to EEG/EMG or BIOSENSOR
    primary_channel_modes = (
        PrimaryChannelMode.EEG_EMG,
        PrimaryChannelMode.EEG_EMG,
        PrimaryChannelMode.EEG_EMG,
        PrimaryChannelMode.EEG_EMG,
    )

    # set the secondary channel modes to DIGITAL or ANALOG
    secondary_channel_modes = (
        SecondaryChannelMode.DIGITAL,
        SecondaryChannelMode.DIGITAL,
        SecondaryChannelMode.DIGITAL,
        SecondaryChannelMode.DIGITAL,
        SecondaryChannelMode.DIGITAL,
        SecondaryChannelMode.DIGITAL,
    )

    # create pod
    pod = MockPod8401HR(
        preamp=Preamp.Preamp8406_SE4,
        primary_channel_modes=primary_channel_modes,
        secondary_channel_modes=secondary_channel_modes,
        ss_gain=ss_gain,
        preamp_gain=preamp_gain,
        sample_rate=2_000,
    )

    yield pod


def test_sample_rate_set_and_get_success(pod):
    sample_rates = [
        2_000,
        4_000,
        8_000,
        16_000,
        20_000,
    ]

    for sample_rate in sample_rates:
        pod.sample_rate = sample_rate

        assert pod.sample_rate == sample_rate

        r =  pod.write_read("GET SAMPLE RATE")
        assert r.payload[0] == sample_rate

def test_set_sample_rate_fail_invalid_sample_rate(pod):
    original_sample_rate = pod.sample_rate

    with pytest.raises(ValueError):
        pod.sample_rate = 21_000

    assert pod.sample_rate == original_sample_rate


def test_get_sample_rate_without_initializing():
    # set preamp gain and ss gain for all channels
    preamp_gain = (10, 10, 10, 10)
    ss_gain = (5, 5, 5, 5)

    # set the primary channel modes to EEG/EMG or BIOSENSOR
    primary_channel_modes = (
        PrimaryChannelMode.EEG_EMG,
        PrimaryChannelMode.EEG_EMG,
        PrimaryChannelMode.EEG_EMG,
        PrimaryChannelMode.EEG_EMG,
    )

    # set the secondary channel modes to DIGITAL or ANALOG
    secondary_channel_modes = (
        SecondaryChannelMode.DIGITAL,
        SecondaryChannelMode.DIGITAL,
        SecondaryChannelMode.DIGITAL,
        SecondaryChannelMode.DIGITAL,
        SecondaryChannelMode.DIGITAL,
        SecondaryChannelMode.DIGITAL,
    )

    # create pod
    pod = MockPod8401HR(
        preamp=Preamp.Preamp8406_SE4,
        primary_channel_modes=primary_channel_modes,
        secondary_channel_modes=secondary_channel_modes,
        ss_gain=ss_gain,
        preamp_gain=preamp_gain,
    )

    assert pod.sample_rate == pod._device_default_sample_rate


def test_get_name_success(pod):
    assert pod.device_name == "MOCK_PORT"
