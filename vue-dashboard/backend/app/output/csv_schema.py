"""Dashboard CSV headers shared by runtime descriptors and recovery validation.

Packet values remain serialized by Morelia; this module opens no hardware and
does not import Morelia, so runtime descriptor construction remains lightweight.
"""

from app.domain.enums import DeviceType


def csv_fieldnames(device_type: DeviceType, pod: object) -> tuple[str, ...]:
    if device_type is DeviceType.POD8206HR:
        return ("time", "EEG1", "EEG2", "EEG3/EMG", "TTL1", "TTL2", "TTL3", "TTL4")
    if device_type is DeviceType.POD8401HR:
        names = ("A", "B", "C", "D")
        mapper = getattr(type(pod), "get_channel_map_for_preamp_device", None)
        if callable(mapper) and getattr(pod, "preamp", None) is not None:
            names = tuple(mapper(pod.preamp).values())
        return ("time", *names, "aEXT0", "aEXT1", "aTTL1", "aTTL2", "aTTL3", "aTTL4")
    if device_type is DeviceType.POD8274D:
        return ("time", "Ch5", "Ch6", "Ch7")
    raise ValueError(f"unsupported CSV device type: {device_type.value!r}")
