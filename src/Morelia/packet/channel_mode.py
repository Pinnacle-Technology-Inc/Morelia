"""
This file contains types used for indicating the types of various channels read from acquisition devices.
Currently, the only device Morelia supports that takes advantage of modal channels is the 8401HR.
"""

from enum import Enum, auto

class PrimaryChannelMode(Enum):
    """Mode for a "primary" channel (i.e. not TTL/AEXT)"""
    EEG_EMG = auto()
    BIOSENSOR = auto()

class SecondaryChannelMode(Enum):
    """Mode for AEXT/TTL channels. Analog channels report a numeric value, as digital values can be high or low (i.e. bypasses the onboard ADC)."""
    ANALOG = auto()
    DIGITAL = auto()
