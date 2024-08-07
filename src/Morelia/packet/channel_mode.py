from enum import Enum, auto

class PrimaryChannelMode(Enum):
    EEG_EMG = auto()
    BIOSENSOR = auto()

class SecondaryChannelMode(Enum):
    ANALOG = auto()
    DIGITAL = auto()
