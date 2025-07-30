"""POD device that streams data."""

__author__      = 'James Hurd'
__maintainer__  = 'James Hurd'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2023, James Hurd'
__email__       = 'sales@pinnaclet.com'

from typing import Self

from Morelia.Devices import Pod

class AquisitionDevice(Pod):
    """
    This class is the parent of any device that can stream (i.e. data aquisiton devices).

    :param port: Serial port to be opened. Used when initializing the COM_io instance.
    :param max_sample_rate: Maximum sample rate supported by the device (in Hz).
    :param baudrate: Baud rate of the opened serial port. Default value is 9600.
    :param device_name: Virtual Name used to indentify device.
    :param get_sample_rate_cmd_no: Command number for the ``GET SAMPLE RATE`` command on the device.
    :param set_sample_rate_cmd_no: Command number for the ``SET SAMPLE RATE`` command on the device.

    """
    def __init__(self, port: str|int, max_sample_rate: int, baudrate:int=9600, device_name: str | None =  None, 
                 get_sample_rate_cmd_no: int = 100, set_sample_rate_cmd_no: int = 101) -> None:

        super().__init__(port, baudrate=baudrate, device_name=device_name) 

        UINT16: int = Pod.get_u(16)
        
        self._commands.add_command(get_sample_rate_cmd_no, 'GET SAMPLE RATE',      (0,),       (UINT16,),    False,   'Gets the current sample rate of the system, in Hz.')
        self._commands.add_command(set_sample_rate_cmd_no, 'SET SAMPLE RATE',      (UINT16,),     (0,),      False,   'Sets the sample rate of the system, in Hz. Valid values are 100 - 2000 currently.')
        

        #initialize as none so that when we ask for the sample rate later, it uses the overidden WriteRead.
        self._sample_rate: int = None

        self._max_sample_rate: int = max_sample_rate

    @property
    def max_sample_rate(self) -> int:
        """Maximum allowable sample rate."""
        return self._max_sample_rate

    @property
    def sample_rate(self) -> int:
        """Currently set sample rate."""

        if self._sample_rate is None:
            response = self.write_read('GET SAMPLE RATE')
            self._sample_rate = response.payload
        return self._sample_rate[0]

    @sample_rate.setter
    def sample_rate(self, rate: int) -> None:
        if rate > self.max_sample_rate:
            raise ValueError(f'The maximum allowable sample rate is {self.max_sample_rate} Hz.')

        self.write_read('SET SAMPLE RATE', (rate,))
        self._sample_rate: int = (rate,)

    @property
    def id(self) -> int:
        """Returns a device's hardware ID."""
        device_id = self.write_read("ID")
        return device_id.payload[0]

    @property
    def type(self) -> int:
        """Returns a device's TYPE number. Each TYPE number corresponds to a specific pod device (see docs). General getter for device TYPE."""
        device_type = self.write_read("TYPE")
        return device_type.payload[0]

    @property
    def pod_type(self) -> str:
        """Gets a device's TYPE number. Maps the number to a pod device string. Returns the pod device string."""
        type_code = str(self.type)
        type_map = {
            "48": "Pod8206HR",
            "52": "Pod8229",
            "46": "Pod8274D",
            "49": "Pod8401HR",
            "50": "Pod8480SC"
        }
        return type_map.get(type_code, "Unknown Pod Device")

    @property
    def serial_number(self) -> str:
        """Returns a device's serial number."""
        return self.write_read("GET SERIAL").payload[0]

    @property
    def firmware_version(self) -> str:
        """Returns a device's firmware version."""
        return self.write_read("GET FIRMWARE").payload[0]

    @property
    def device_name(self) -> str:
        """Returns a device's virtual name."""
        return self.write_read("GET NAME").payload[0]

    @device_name.setter
    def device_name(self, value: str):
        """Sets a device's virtual name."""
        self.write_packet("SET NAME", value)

    @property
    def description(self) -> str:
        """Returns a device's description."""
        return self.write_read("GET DESCRIPTION").payload[0]

    @description.setter
    def description(self, value: str):
        """Sets a device's description."""
        self.write_packet("SET DESCRIPTION", value)

    @property
    def alias(self) -> str:
        """Returns a device's alias."""
        return self.write_read("GET ALIAS").payload[0]

    @alias.setter
    def alias(self, value: str):
        """Sets a device's alias."""
        self.write_packet("SET ALIAS", value)

    @property
    def alias_color(self) -> str:
        """Returns a device's alias color."""
        return self.write_read("GET ALIASCOLOR").payload[0]

    @alias_color.setter
    def alias_color(self, value: str):
        """Sets a device's alias color."""
        self.write_packet("SET ALIASCOLOR", value)

    @property
    def annotations_enabled(self) -> bool:
        """Checks if annotations are enabled for the device."""
        return self.write_read("GET ANNOTATIONS").payload[0] == "ENABLED"

    @annotations_enabled.setter
    def annotations_enabled(self, enabled: bool):
        """Enables or disables annotations for the device."""
        self.write_packet("SET ANNOTATIONS", "ENABLED" if enabled else "DISABLED")

    @property
    def udp_enabled(self) -> bool:
        """Checks if UDP is enabled for the device."""
        return self.write_read("GET UDP").payload[0] == "ENABLED"

    @udp_enabled.setter
    def udp_enabled(self, enabled: bool):
        """Enables or disables UDP for the device."""
        self.write_packet("SET UDP", "ENABLED" if enabled else "DISABLED")

    @property
    def udp_port(self) -> int:
        """Returns the UDP port number for the device."""
        return int(self.write_read("GET UDPPORT").payload[0])

    @udp_port.setter
    def udp_port(self, value: int):
        """Sets the UDP port number for the device."""
        self.write_packet("SET UDPPORT", str(value))


    @staticmethod
    def combine_property_maps(base_map: dict, override_map: dict) -> dict:
        """
        Combines two property maps (base map and acquisition device map). The override_map (acquisition device map) takes precedence.
        Nested dictionaries are merged recursively.

        :param base_map: The base property map (e.g., Pod._property_map)
        :param override_map: The device-specific property map (e.g., Pod8206HR._property_map)
        :return: A new merged property map
        """
        def merge_dicts(base, acq):
            result = dict(base)
            for key, val in acq.items():
                if (
                    key in result
                    and isinstance(result[key], dict)
                    and isinstance(val, dict)
                ):
                    result[key] = merge_dicts(result[key], val)
                else:
                    result[key] = val
            return result

        return merge_dicts(base_map, override_map)

    def validate_configuration(self, sent_config: dict) -> bool:
        """
        Validates that the configuration sent to the device matches the configuration
        currently on the device.

        :param sent_config: The configuration dictionary that was sent/applied to the device.
        :return: True if the device config matches the sent config, False otherwise.
        """
        # Keys to skip during validation (sections or properties)
        skip_keys = {"title", "filename"}

        def flatten(config, parent_key='', sep='.'):
            items = []
            for k, v in config.items():
                if k in skip_keys:
                    continue
                else:
                    new_key = f"{parent_key}{sep}{k}" if parent_key else k
                    if isinstance(v, dict):
                        items.extend(flatten(v, new_key, sep=sep).items())
                    else:
                        items.append((new_key, v))
            return dict(items)

        # Get current config from device
        current_config = self._collect_config()

        # Flatten both configs for comparison
        flat_sent = flatten(sent_config)
        flat_current = flatten(current_config)

        # Only compare keys present in sent_config (ignore extra keys from device)
        mismatches = {}
        for key, sent_value in flat_sent.items():
            current_value = flat_current.get(key, None)
            if str(sent_value) != str(current_value):
                mismatches[key] = {"sent": sent_value, "device": current_value}

        if mismatches:
            print("[VALIDATION FAILED] The following configuration values do not match:")
            for key, vals in mismatches.items():
                print(f"  {key}: sent={vals['sent']} device={vals['device']}")
            return False

        print("[VALIDATION SUCCESS] Device configuration matches sent configuration.")
        return True
                    
    """Default Property Map for Pod Devices"""
    _property_map = {
        "identification": {
            "id": "id",
            "type": "type",
            "pod_type": "pod_type",
            "serial_number": "serial_number",
            "firmware_version": "firmware_version",
            "device_name": "device_name",
        },
        "metadata": {
            "description": "description",
            "alias": "alias",
            "alias_color": "alias_color",
        },
        "features": {
            "annotations_enabled": "annotations_enabled",
            "udp_enabled": "udp_enabled",
            "udp_port": "udp_port",
        }
    }
    
    def __enter__(self) -> Self:

        #no WriteRead, because the confirmation packet may arrive
        #after streaming data due to a race condition in the device's
        #firmware. Therefore, we leave dealing with the response packet
        #to the user.
        self.write_packet('STREAM', 1)

        return self

    def __exit__(self, *args, **kwargs) -> bool:

        self.write_packet('STREAM', 0)
        
        #get any packets that may have arrived between the user ending stream
        #and the command being received from the device + plus the response
        #packet from earlier.
        while True:
            try:
                self.read_pod_packet(timeout_sec=1)
            except TimeoutError:
                break
        
        #explicitly tell the context manager to propagate execptions.
        return False
