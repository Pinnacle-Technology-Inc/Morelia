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
    def pod_info(self) -> dict: 
        """Gets pod identification info for ease of use. Returns the information in the form of a dictionary"""
        print("[DEBUG] inside pod_info")
        info = {
                "device_name" : self.device_name,
                "device_id" : self.id,
                "type_number" : self.type,
                "device_type" : self.pod_type
            }
        print(info)
        return info


    def validate_config(self, expected_config: dict, skip_keys: set | None = None) -> dict:
        """Validates the current device configuration against an expected configuration.

        Compares the expected config dictionary to the device's actual config 
        obtained via getters, recursively checking nested dictionaries.

        Keys in the skip_keys set (default includes 'title' and 'filename') 
        will be ignored during comparison.

        :param expected_config: The expected configuration dictionary to validate against.
        :param skip_keys: Optional set of keys to skip during comparison (e.g., metadata keys).
        :return: A dictionary mapping config keys (dot notation) to tuples of (expected, actual) values
                 for any differences found. Empty if no differences.
        """        
        
        # skip_keys often used to skip comparisons between SET/GET for GET properties only 
        if self.pod_type == "Pod8206HR":
            skip_keys = {"title", "filename", "filter_config", "ttl_port"}
        elif self.pod_type == "Pod8229":
            skip_keys = {"title", "filename"}
        elif self.pod_type == "Pod8274D":
            skip_keys = {"title", "filename"}
        elif self.pod_type == "Pod8401HR":
            skip_keys = {"title", "filename"}
        elif self.pod_type == "Pod8480SC":
            skip_keys = {"title", "filename"}
        elif skip_keys is None:
            skip_keys = {"title", "filename"}  # Add any other keys you want to skip here
        else:
            skip_keys = set(skip_keys)
            skip_keys.update({"title", "filename"})

        actual_config = self._collect_config()
        diffs = {}

        def normalize(val):
            """Convert config values to a consistent Python type for comparison."""
            import numpy as np

            # unwrap numpy scalars
            if isinstance(val, np.generic):
                return val.item()

            # handle strings
            if isinstance(val, str):
                val = val.strip()
                # try to cast to int
                if val.isdigit():
                    return int(val)
                # try to cast to float
                try:
                    return float(val)
                except ValueError:
                    return val  # leave as string if not numeric

            # normalize floats
            if isinstance(val, float):
                return round(val, 6)

            return val


        def recursive_diff(expected, actual, path=""):
            """Recursively compare expected and actual dictionaries, 
            collecting differences in diffs dictionary.

            :param expected: Expected config dictionary or value
            :param actual: Actual config dictionary or value
            :param path: String path of nested keys (dot separated)
            """
            for key in expected:
                if key in skip_keys:
                    continue
                expected_val = expected[key]
                actual_val = actual.get(key) if isinstance(actual, dict) else None

                current_path = f"{path}.{key}" if path else key

                if isinstance(expected_val, dict) and isinstance(actual_val, dict):
                    recursive_diff(expected_val, actual_val, current_path)
                else:
                    norm_expected = normalize(expected_val)
                    norm_actual = normalize(actual_val)

                    if norm_expected != norm_actual:
                        diffs[current_path] = (
                            (norm_expected, type(norm_expected)),
                            (norm_actual, type(norm_actual)),
                        )

        recursive_diff(expected_config, actual_config)
        return diffs

    """Default Property Map for Pod Devices"""
    property_map = {
        "sample_rate": {
            "sample_rate": "sample_rate",
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
