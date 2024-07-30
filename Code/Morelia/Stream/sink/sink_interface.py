"""Interface for dataflow sink."""

__author__      = 'James Hurd'
__maintainer__  = 'Thresa Kelly'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2024, Thresa Kelly'
__email__       = 'sales@pinnaclet.com'

import abc

from Morelia.Packets import PacketBinary
from Morelia.Devices import Pod8206HR, Pod8401HR, Pod8274D

class SinkInterface(metaclass=abc.ABCMeta):

    @classmethod
    def __subclasshook__(cls, subclass) -> None:
        return ( hasattr(subclass, 'flush') and callable(subclass.flush) ) or NotImplemented

    #TODO: typehint packet
    @abc.abstractmethod
    def flush(self, timestamp: int, packet) -> None:
        """Send data to destination (e.g. and EDF file)."""
        raise NotImplementedError
