from enum import Enum, auto

class DigitalSignal(Enum):
    LOW = auto()
    HIGH = auto()

    def __str__(self):
        return "0" if self is DigitalSignal.LOW else "1"

    def __float__(self):
        return 0.0 if self is DigitalSignal.LOW else 1.0
