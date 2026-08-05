"""Interface for dataflow sink."""

__author__      = 'James Hurd'
__maintainer__  = 'Thresa Kelly'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2024, Thresa Kelly'
__email__       = 'sales@pinnaclet.com'

import abc
from typing import Any
from Morelia.packet.data import DataPacket
from Morelia.Devices import Pod8206HR, Pod8401HR, Pod8274D

from Morelia.ParamSchema.ParamSchema import ParamSchema
from collections.abc import Callable, Mapping

_OBSERVE_ON_SCHEDULER_VALUES = frozenset({None, "thread_pool", "new_thread"})

_DEVICE_PREFERENCE_KEYS = frozenset({"name", "type", "value", "ProductNumber", "SerialNumber"})
_DEVICE_PREFERENCE_STRING_KEYS = ("name", "type", "ProductNumber", "SerialNumber")

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

    @abc.abstractmethod
    def get_dict(self) -> dict[str, Any]:
        """Obtains sink __init__ argument values to use for process pickling"""
        pass

    @property
    @abc.abstractmethod
    def param_schema(self) -> ParamSchema:
        pass

    def _check_observe_on_scheduler(self, value: object) -> None:
        if value not in _OBSERVE_ON_SCHEDULER_VALUES:
            raise ValueError('observe_on_scheduler must be one of: null, "thread_pool", "new_thread"')

    def _check_bool(self, value: object, *, key: str) -> None:
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be a boolean")

    def _check_device_preferences(self, value: object) -> None:
        if not isinstance(value, tuple):
            raise ValueError("device_preferences must be a list of preference objects")
        for entry in value:
            if not isinstance(entry, Mapping):
                raise ValueError("each device_preferences entry must be an object")
            keys = set(entry)
            if keys != _DEVICE_PREFERENCE_KEYS:
                missing = _DEVICE_PREFERENCE_KEYS - keys
                unknown = keys - _DEVICE_PREFERENCE_KEYS
                parts = []
                if missing:
                    parts.append(f"missing {', '.join(sorted(missing))}")
                if unknown:
                    parts.append(f"unknown {', '.join(sorted(unknown))}")
                raise ValueError(f"device_preferences entry has {'; '.join(parts)}")
            for key in _DEVICE_PREFERENCE_STRING_KEYS:
                if not isinstance(entry[key], str) or not entry[key].strip():
                    raise ValueError(f"device_preferences entry {key!r} must be a non-empty string")

    def _check_nonempty_string(self, value: object, *, key: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty string")

    def _check_positive_number(self, value: object, *, key: str) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"{key} must be a positive number")

    def _check_positive_int(self, value: object, *, key: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{key} must be a positive integer")

    def _check_port(self, value: object) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or not (1 <= value <= 65535):
            raise ValueError("port must be an integer in 1..65535")

    def _check_channel_names(value: object) -> None:
        if not isinstance(value, tuple) or not value:
            raise ValueError("channel_names must be a non-empty list of non-empty strings")
        for name in value:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("channel_names must be a non-empty list of non-empty strings")
