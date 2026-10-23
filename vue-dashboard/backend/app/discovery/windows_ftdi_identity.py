"""Match observed USB base serials/channels, then unambiguous ContainerIDs.

Keep exact open selectors and separate channels. Registry snapshots belong to
one inventory; no persistent application alias cache or USB opens are needed.
"""

from __future__ import annotations

import sys
from collections import defaultdict

_USB = r"SYSTEM\CurrentControlSet\Enum\USB"
_BUS = r"SYSTEM\CurrentControlSet\Enum\FTDIBUS"
# PID -> allowed channels, D2XX device types. Multi-port native selectors
# include a channel; single-port selectors use the USB base serial.
_PROFILES = {
    0x6001: ("A", (5,)),       # FT232R / FT245R
    0x6010: ("AB", (4, 6)),   # FT2232C / FT2232H
    0x6011: ("ABCD", (7,)),   # FT4232H
    0x6014: ("A", (8,)),      # FT232H
}


def _subkeys(registry, key):
    index = 0
    while True:
        try:
            yield registry.EnumKey(key, index)
            index += 1
        except OSError as exc:
            if getattr(exc, "winerror", None) == 259:
                return
            raise


def _value(registry, key, name):
    try:
        value = registry.QueryValueEx(key, name)[0]
    except OSError:
        return None
    return value if isinstance(value, str) and value else None


def _registry_records() -> tuple[list[dict], list[dict]]:
    """Read USB parents and VCP endpoints even when ContainerID is absent."""
    if sys.platform != "win32":
        return [], []
    import winreg

    parents, children = [], []
    for pid in _PROFILES:
        try:
            path = f"{_USB}\\VID_0403&PID_{pid:04X}"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as root:
                for serial in _subkeys(winreg, root):
                    with winreg.OpenKey(root, serial) as key:
                        parents.append({
                            "serial": serial, "pid": pid,
                            "container": _value(winreg, key, "ContainerID"),
                        })
        except FileNotFoundError:
            continue
        except OSError:
            return [], []  # Partial reads cannot establish uniqueness.
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _BUS) as root:
            for name in _subkeys(winreg, root):
                parts = name.split("+", 2)
                if len(parts) != 3 or parts[0].upper() != "VID_0403":
                    continue
                try:
                    pid = int(parts[1][4:], 16) if parts[1].upper().startswith("PID_") else 0
                except ValueError:
                    continue
                if pid not in _PROFILES:
                    continue
                with winreg.OpenKey(root, name) as device:
                    for instance in _subkeys(winreg, device):
                        with winreg.OpenKey(device, instance) as key:
                            container = _value(winreg, key, "ContainerID")
                            try:
                                with winreg.OpenKey(key, "Device Parameters") as parameters:
                                    port = _value(winreg, parameters, "PortName")
                            except FileNotFoundError:
                                port = None
                        if port:
                            children.append({
                                "serial": parts[2], "pid": pid, "port": port,
                                "container": container,
                            })
    except OSError:
        return [], []
    return parents, children


def _serial(value):
    return isinstance(value, str) and bool(value) and value == value.strip()


def _container(record):
    value = record.get("container")
    return value.lower() if isinstance(value, str) and value else None


def build_bindings(parents: list[dict], children: list[dict], *, _conflicts=None) -> list[dict]:
    """Build aliases in O(parents + children), with bounded serial lengths.

    A VCP binding is applied only to the currently enumerated serial/COM pair.
    Conflicting evidence is rejected instead of being rescued by fallback.
    """
    by_serial, by_container = defaultdict(list), defaultdict(list)
    child_containers = defaultdict(list)
    conflicts = _conflicts if _conflicts is not None else {"vcp": set(), "native": set()}
    conflicted_containers = set()

    def reject(child, *, exact=False, suffixed=False, container=False):
        """Retain known contradictions so raw string matching cannot bypass them."""
        pid, alias = child.get("pid", 0x6001), child["serial"]
        conflicts["vcp"].add((alias, child["port"].upper()))
        channels = _PROFILES[pid][0]
        if exact:
            for channel in channels:
                conflicts["native"].add((pid, alias if len(channels) == 1 else alias + channel))
        if suffixed:
            conflicts["native"].add((pid, alias[:-1] if len(channels) == 1 else alias))
        if container and _container(child):
            conflicted_containers.add(_container(child))
    for parent in parents:
        pid = parent.get("pid", 0x6001)
        if pid not in _PROFILES or not _serial(parent.get("serial")):
            continue
        by_serial[pid, parent["serial"]].append(parent)
        if _container(parent):
            by_container[_container(parent)].append(parent)
    for child in children:
        if _container(child):
            child_containers[_container(child)].append(child)

    candidates = []
    for child in children:
        pid = child.get("pid", 0x6001)
        alias, port = child.get("serial"), child.get("port")
        if pid not in _PROFILES or not _serial(alias) or not _serial(port):
            continue
        channels, _ = _PROFILES[pid]
        exact = by_serial.get((pid, alias), [])
        suffixed = by_serial.get((pid, alias[:-1]), []) if alias[-1] in "ABCD" else []
        if exact and suffixed:
            reject(child, exact=True, suffixed=True)
            continue  # A real base serial may itself end in A-D.
        if suffixed:
            if len(suffixed) != 1 or alias[-1] not in channels:
                reject(child, suffixed=True)
                continue
            parent, channel = suffixed[0], alias[-1]
        elif exact:
            if len(exact) != 1 or len(channels) != 1:
                reject(child, exact=True)
                continue
            parent, channel = exact[0], "A"
        else:
            container = _container(child)
            matches = by_container.get(container, [])
            if (not container or len(matches) != 1
                    or len(child_containers[container]) != 1 or len(channels) != 1):
                if matches:
                    reject(child, container=True)
                continue  # Container alone cannot select a multi-port channel.
            parent, channel = matches[0], "A"
            if parent.get("pid", 0x6001) != pid:
                reject(child, container=True)
                continue
            if len(by_serial[pid, parent["serial"]]) != 1:
                reject(child, container=True)
                continue
        parent_container, child_container = _container(parent), _container(child)
        if parent_container and child_container and parent_container != child_container:
            reject(child, exact=bool(exact), suffixed=bool(suffixed), container=True)
            continue
        # A matching container cannot conceal a second USB parent. Indexed
        # counts keep even deliberately ambiguous inventories linear.
        if child_container:
            matches = by_container.get(child_container, [])
            if matches and (len(matches) != 1 or matches[0] is not parent):
                reject(child, exact=bool(exact), suffixed=bool(suffixed), container=True)
                continue
        base = parent["serial"]
        native = base if len(channels) == 1 else base + channel
        candidates.append({
            "native_serial": native, "physical_id": native,
            "hardware_id": alias, "port": port, "pid": pid,
            "base_serial": base, "channel": channel,
            "identity_evidence": (
                "usb_serial_channel" if exact or suffixed else "windows_container_id"
            ),
        })

    # Never let the first duplicate channel/port win.
    native_counts, port_counts = defaultdict(int), defaultdict(int)
    for binding in candidates:
        native_counts[binding["native_serial"]] += 1
        port_counts[binding["port"].upper()] += 1
    for binding in candidates:
        if native_counts[binding["native_serial"]] > 1 or port_counts[binding["port"].upper()] > 1:
            conflicts["native"].add((binding["pid"], binding["native_serial"]))
            conflicts["vcp"].add((binding["hardware_id"], binding["port"].upper()))
    # Expand conflicting container groups once, not once per child.
    for parent in parents:
        pid = parent.get("pid", 0x6001)
        if (pid in _PROFILES and _serial(parent.get("serial"))
                and _container(parent) in conflicted_containers):
            channels = _PROFILES[pid][0]
            for channel in channels:
                native = parent["serial"] if len(channels) == 1 else parent["serial"] + channel
                conflicts["native"].add((pid, native))
    return [binding for binding in candidates
            if (binding["pid"], binding["native_serial"]) not in conflicts["native"]
            and (binding["hardware_id"], binding["port"].upper()) not in conflicts["vcp"]]


def verified_bindings() -> list[dict]:
    """One read-only snapshot; saved application aliases are not required."""
    return build_bindings(*_registry_records())


class _BindingIndex:
    def __init__(self, bindings, conflicts=None):
        self.conflicts = conflicts or {"vcp": set(), "native": set()}
        self.native = defaultdict(list)
        self.vcp = defaultdict(list)
        for binding in bindings:
            self.native[binding.get("pid", 0x6001), binding["native_serial"]].append(binding)
            self.vcp[binding["hardware_id"], binding["port"].upper()].append(binding)

    def annotate(self, endpoint):
        if endpoint.get("transport") == "d2xx":
            device_id = endpoint.get("id")
            if not isinstance(device_id, int) or device_id >> 16 != 0x0403:
                return dict(endpoint)
            pid = device_id & 0xFFFF
            if pid not in _PROFILES or endpoint.get("type") not in _PROFILES[pid][1]:
                return dict(endpoint)
            key = (pid, endpoint.get("address"))
            if key in self.conflicts["native"]:
                return {**endpoint, "identity_conflict": True}
            matches = self.native.get(key, [])
        elif endpoint.get("transport") == "vcp":
            key = (endpoint.get("hardware_id"), str(endpoint.get("address", "")).upper())
            if key in self.conflicts["vcp"]:
                return {**endpoint, "identity_conflict": True}
            matches = self.vcp.get(key, [])
        else:
            return dict(endpoint)
        if len(matches) != 1:
            return dict(endpoint)
        binding = matches[0]
        if endpoint.get("transport") == "vcp" and (
            endpoint.get("vid", 0x0403) != 0x0403
            or endpoint.get("pid", binding.get("pid", 0x6001)) != binding.get("pid", 0x6001)
        ):
            return dict(endpoint)
        return {
            **endpoint,
            "hardware_id": binding["hardware_id"],
            "physical_id": binding["physical_id"],
            "aliases": tuple(dict.fromkeys((binding["hardware_id"], binding["native_serial"]))),
            "identity_evidence": binding["identity_evidence"],
            **{key: binding[key] for key in ("base_serial", "channel") if key in binding},
        }


def annotate_endpoints(endpoints: list[dict], *, bindings: list[dict] | None = None) -> list[dict]:
    """Annotate an inventory with one registry read and indexed lookups."""
    conflicts = {"vcp": set(), "native": set()}
    if bindings is None:
        bindings = build_bindings(*_registry_records(), _conflicts=conflicts)
    index = _BindingIndex(bindings, conflicts)
    return [index.annotate(endpoint) for endpoint in endpoints]


def annotate_endpoint(endpoint: dict, *, bindings: list[dict] | None = None) -> dict:
    """Compatibility entry point; inventory callers use annotate_endpoints."""
    return annotate_endpoints([endpoint], bindings=bindings)[0]
