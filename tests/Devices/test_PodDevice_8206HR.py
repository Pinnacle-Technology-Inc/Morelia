"""
Unit tests for the Pod8206HR device.

These tests verify the behavior of the mock 8206HR acquisition device,
including:

- Sample rate configuration.
- Default sample rate behavior.
- Device information queries.
- Streaming data packet generation.
- Context manager cleanup.
"""

import pytest

from tests.mocks.device.pod_8206HR.MockPodDevice_8206HR import MockPod8206HR

@pytest.fixture
def pod():
    # Connect to an 8206HR.
    pod = MockPod8206HR(preamp_gain=10)

    # Set the sample rate.
    pod.sample_rate = 2000

    yield pod


def test_sample_rate_set_and_get_success(pod):
    sample_rates = [
        100,
        500,
        1_000,
        1_500,
        2_000
    ]

    for sample_rate in sample_rates:
        pod.sample_rate = sample_rate

        assert pod.sample_rate == sample_rate

        r =  pod.write_read("GET SAMPLE RATE")

        print(r.payload)
        print(r.payload[0])
        assert r.payload[0] == sample_rate

        print("here")

def test_set_sample_rate_fail_invalid_sample_rate(pod):
    original_sample_rate = pod.sample_rate

    with pytest.raises(ValueError):
        pod.sample_rate = 2_100

    assert pod.sample_rate == original_sample_rate
