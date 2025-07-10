"""Interface for dataflow sink."""

__author__      = 'James Hurd'
__maintainer__  = 'Thresa Kelly'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2024, Thresa Kelly'
__email__       = 'sales@pinnaclet.com'

import abc

from Morelia.packet.data import DataPacket
from Morelia.Devices import Pod8206HR, Pod8401HR, Pod8274D, AcquisitionDevice

class SinkInterface(metaclass=abc.ABCMeta):
    """
    Interface that data sinks **must** implement.
    """

    @classmethod
    def __subclasshook__(cls, subclass) -> None:
        return ( hasattr(subclass, 'flush') and callable(subclass.flush) ) or NotImplemented

    @abc.abstractmethod
    def flush(self, timestamp: int, packet: DataPacket) -> None:
        """Send data to destination (e.g. and EDF file)."""
        raise NotImplementedError

    def convert_to_device(self, pod_tuple: tuple[str, dict]):
        if pod_tuple[0] == "Pod8206HR":
            print(pod_tuple[1])
            return Pod8206HR(**pod_tuple[1])
        elif pod_tuple[0] == "Pod8401HR":
            return Pod8401HR(**pod_tuple[1])
        elif pod_tuple[0] == "Pod8274D":
            return Pod8274D(**pod_tuple[1])
        else:
            raise ValueError(f"{pod_tuple} is not an expected input for convert_to_device")

    def get_device_type_and_dict(self, pod: AcquisitionDevice):

        pod_string = ""
        if isinstance(pod, Pod8206HR):
            pod_string = "Pod8206HR"
        elif isinstance(pod, Pod8401HR):
            pod_string = "Pod8401HR"
        elif isinstance(pod, Pod8274D):
            pod_string = "Pod8274D"
        else:
            raise ValueError(f"Device '{pod._device_name}' cannot be streamed from!")
        #pod.close_port()
        return (pod_string, pod.get_dict()) 