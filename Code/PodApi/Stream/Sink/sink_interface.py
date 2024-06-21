import abc

from PodApi.Packets import Packet
from PodApi.Stream.PodHandler import Drain8206HR, Drain8274D, Drain8401HR
from PodApi.Devices import Pod8206HR, Pod8401HR, Pod8274D

class SinkInterface(metaclass=abc.ABCMeta):

    @classmethod
    def __subclasshook__(cls, subclass) -> None:
        return ( hasattr(subclass, 'flush') and callable(subclass.flush) ) or NotImplemented

    @staticmethod
    def get_device_handler(pod: Pod8206HR | Pod8274D | Pod8401HR) -> Drain8206HR | Drain8274D | Drain8401HR:
        if isinstance(pod,Pod8206HR):
            return Drain8206HR()

        if isinstance (pod,Pod8401HR):
            return Drain8401HR()

        if isinstance(pod,Pod8274D):
            return Drain8274D()

        #TODO: say which device?
        raise ValueError('Streaming from this device is not supported!')

    @abc.abstractmethod
    async def flush(self, timestamps: list[float], raw_data: list[Packet|None]) -> None:
        """Send data to destination (e.g. and EDF file)."""
        raise NotImplementedError
