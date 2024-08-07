from enum import Enum, auto

class TTL(Enum):
    LOW = auto()
    HIGH = auto()

    def __str__(self):
        return "0" if self is TTL.LOW else "1"
