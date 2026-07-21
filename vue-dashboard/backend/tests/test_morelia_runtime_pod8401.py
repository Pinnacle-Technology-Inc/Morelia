from enum import Enum, auto
from types import SimpleNamespace

import pytest

from app.runtime_child.morelia import MoreliaRuntime


class _Preamp(Enum):
    Preamp8407_SE = auto()


class _PrimaryChannelMode(Enum):
    EEG_EMG = auto()
    BIOSENSOR = auto()


class _SecondaryChannelMode(Enum):
    ANALOG = auto()
    DIGITAL = auto()


class _Pod8401HR:
    def __init__(
        self,
        port,
        preamp,
        primary_channel_modes,
        secondary_channel_modes,
        *,
        ss_gain,
        preamp_gain,
        baudrate,
        device_name,
        use_d2xx,
    ):
        self.port = port
        self.preamp = preamp
        self.primary_channel_modes = primary_channel_modes
        self.secondary_channel_modes = secondary_channel_modes
        self.ss_gain = ss_gain
        self.preamp_gain = preamp_gain
        self.baudrate = baudrate
        self.device_name = device_name
        self.use_d2xx = use_d2xx


def test_build_pod8401hr_passes_six_secondary_modes_to_morelia():
    device_flow = SimpleNamespace(
        port="COM7",
        name="left-8401",
        parameters={
            "preamp": "Preamp8407_SE",
            "primary_channel_modes": ["BIOSENSOR", "EEG_EMG", "EEG_EMG", "EEG_EMG"],
            "secondary_channel_modes": [
                "DIGITAL",
                "DIGITAL",
                "DIGITAL",
                "DIGITAL",
                "DIGITAL",
                "DIGITAL",
            ],
            "ss_gain": [1, 5, 5, 5],
            "preamp_gain": [None, 10, 10, 10],
        },
    )

    pod = MoreliaRuntime._build_pod8401hr(
        _Pod8401HR,
        _Preamp,
        _PrimaryChannelMode,
        _SecondaryChannelMode,
        device_flow,
    )

    assert pod.secondary_channel_modes == (
        _SecondaryChannelMode.DIGITAL,
        _SecondaryChannelMode.DIGITAL,
        _SecondaryChannelMode.DIGITAL,
        _SecondaryChannelMode.DIGITAL,
        _SecondaryChannelMode.DIGITAL,
        _SecondaryChannelMode.DIGITAL,
    )
    assert pod.primary_channel_modes == (
        _PrimaryChannelMode.BIOSENSOR,
        _PrimaryChannelMode.EEG_EMG,
        _PrimaryChannelMode.EEG_EMG,
        _PrimaryChannelMode.EEG_EMG,
    )
    assert pod.preamp_gain == (None, 10, 10, 10)


def test_build_pod8401hr_rejects_four_secondary_modes():
    device_flow = SimpleNamespace(
        port="COM7",
        name="left-8401",
        parameters={
            "preamp": "Preamp8407_SE",
            "primary_channel_modes": ["BIOSENSOR", "EEG_EMG", "EEG_EMG", "EEG_EMG"],
            "secondary_channel_modes": ["DIGITAL", "DIGITAL", "DIGITAL", "DIGITAL"],
        },
    )

    with pytest.raises(ValueError, match="secondary_channel_modes must be a 6-tuple"):
        MoreliaRuntime._build_pod8401hr(
            _Pod8401HR,
            _Preamp,
            _PrimaryChannelMode,
            _SecondaryChannelMode,
            device_flow,
        )
