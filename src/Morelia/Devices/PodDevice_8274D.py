# local imports 
import time
from Morelia.Devices import Pod, AcquisitionDevice

from Morelia.packet.data import DataPacket8274D
from Morelia.packet.legacy import Packet

from Morelia.packet import ControlPacket
import Morelia.packet.conversion as conv

from functools import partial

# authorship
__author__      = "Sree Kondi"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Sree Kondi", "Thresa Kelly", "Seth Gabbert", 'Sean Gupta']
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Pod8274D(AcquisitionDevice) : 
    """Handle communication with an 8274D POD device.

    This class initializes the serial port, configures device-specific commands,
    and optionally connects to a remote 8274 device by serial number during initialization.
    If ``device_serial_number`` is provided, the constructor will automatically scan for
    and connect to the specified device.

    :param port: Serial port to be opened. Used when initializing the COM_io instance.
    :param baudrate: Baud rate of the opened serial port. Defaults to 921600 bps.
    :param device_name: Virtual name used to identify the device locally.
    :param device_serial_number: Serial number of the remote 8274D device to connect to 
        (printed on device).
        If provided, the device will be automatically located and connected during
        initialization. Defaults to None (no automatic connection).
    :param scan_timeout_sec: Maximum number of seconds to scan for the device when
        ``device_serial_number`` is provided. Defaults to 15 seconds.
    """

    # Device primary and secondary gain map
    DEVICE_GAINS = {
        # Device name   # Primary gain  # Secondary gain
        "8274-SL":      (100,           26),
        "8274-SE":      (100,           26),
        "8274-SE3":     (100,           26),
        "8274-IE":      (100,           13),
    }

    def __init__(self, port: str|int, baudrate:int=921600, device_name: str | None = None, device_serial_number: str | None = None, scan_timeout_sec: int|float = 15, sample_rate: int | None = None) -> None :
        """Initialize the 8274D device and optionally connect to a remote device.

        Sets up the serial port, loads command definitions for the 8274D, initializes
        the device, enables local scanning, and optionally connects to a remote device
        if a ``device_serial_number`` is provided.
        """
        # initialize POD_Basics
        super().__init__(port, 1024, baudrate=baudrate, device_name=device_name, get_sample_rate_cmd_no=208, set_sample_rate_cmd_no=210)
        if sample_rate is not None:
            self._sample_rate = sample_rate

        # get constants for adding commands 
        UINT8  = Pod.get_u(8)
        UINT16 = Pod.get_u(16)
        UINT32 = Pod.get_u(32)
        NO_VALUE = Pod.get_u(0)
        # add device specific commands
        self._commands.add_command(100, 'LOCAL SCAN',               (UINT8,),                   (UINT16,),              False, 'Enables or disables scan.  1 enables, 0 disables.  Returns SL_STATUS_T status code, 0x0000 is success, all others are error codes.')
        self._commands.add_command(101, 'DEVICE LIST INFO',         (UINT8,),                   tuple([UINT8]*24),      False, 'Information string about a scanned device - includes advertising index, bluetooth address, and device name.')
        self._commands.add_command(102, 'LOCAL CONNECTION INFO',    (UINT8,),                   tuple([UINT8]*24),      False, 'Information string about a connected device - includes connection index, bluetooth address, and device name.')
        self._commands.add_command(103, 'LOCAL CONNECTION STATUS',  (0,),                    (UINT8,),               False, 'Returns a bitmask indicating which connection slots are occupied.  0 = unused, 1 = connected.  Only bits 0-3 are relevant.')
        self._commands.add_command(104, 'DISCONNECT ALL',           (0,),                    (UINT8,),               False, 'Attempts to disconnect all connections.  Returns a bitmask indicating which connections have been removed.  0=unchanged, 1=disconnected.  Only bits 0-3 are relevant.')
        self._commands.add_command(105, 'SET BAUD RATE',            (UINT8,),                   (UINT8,),               False, 'Sets the local baud rate of the device.  Sends a reponse packet with the requested value before changing rates.  0 = 115200, 1 = 460800, 2=921600.  ')
        self._commands.add_command(106, 'CHANNEL SCAN',             (UINT8,),                   tuple([UINT8]*5),       False, 'Enables the bluetooth channel scan.  0 = disable, 1 = enable.  After enabling, periodic packets of this type will be sent back with a 5 byte payload of channel availability data,  bits 0-36, 1 = available and 0 = unavailable.')
        # self._commands.add_command(128, 'GET WAVEFORM',           (0,),                    (UINT16,),              False, 'Requests to read the stored FSCV waveform from the remote device.  Reply is SL_STATUS_T status code; 0x0000 is success, all others are error codes.')
        # self._commands.add_command(129, 'GET WAVEFORM REPLY',     (0,),                    (NO_VALUE,),          False, 'The waveform descriptor returned from the remote device.  Variable length.')
        # self._commands.add_command(130, 'SET WAVEFORM',           (NO_VALUE,),              (UINT16,),              False, 'Sends the waveform to the remove device.  Reply is SL_STATUS_T.')
        self._commands.add_command(131, 'GET PERIOD',               (0,),                    (UINT16,),              False, 'Requests the FSCV sample period.  Reply is SL_STATUS_T.')
        self._commands.add_command(132, 'GET PERIOD REPLY',         (0,),                    (UINT16,),              False, 'The period returned from the remote device in 1/32,758ths of a second.')
        self._commands.add_command(133, 'SET PERIOD',               (UINT16,),                  (0,),                False, 'Sends the period to the remote device.  Reply is SL_STATUS_T')
        # self._commands.add_command(134, 'GET STIMULUS',           (0,),                    (UINT16,),              False, 'Requests to read the stimulus config from the remote device.  Reply is SL_STATUS_T')
        # self._commands.add_command(135, 'GET STIMULUS REPLY',     (0,),                    (NO_VALUE,),          False, 'Sends the period to the remote device.  Reply is SL_STATUS_T')
        # self._commands.add_command(136, 'SET STIMULUS',           (UINT32, UINT32, UINT32, UINT32,),   (0,),                False, 'Sends a  stimulus command to the remote device.  This will initiate the requested stimulus at the next waveform start.  See below for details.')
        self._commands.add_command(200, 'CONNECT',                  (UINT8,),                   (UINT16,),              False, 'Requests a connection to the given advertising slot.  Returns connection status. ')
        self._commands.add_command(201, 'CONNECT REPLY',            (0,),                    (0,),                False, 'Indicates a connection completed successfully.')
        self._commands.add_command(202, 'DISCONNECT',               (UINT8,),                   (UINT16,),              False, 'Requests to disconnect from a given connection slot.  Returns a disconnect status.')
        self._commands.add_command(203, 'DISCONNECT REPLY',         (0,),                    (0,),                False, 'Indicates the disconnect completed successfully')
        self._commands.add_command(204, 'GET SERIAL NUMBER',        (0,),                    (UINT16,),              False, 'Requests a read - returns SL_STATUS_T value.  0x0000 is success, all others are error codes.')
        self._commands.add_command(205, 'GET SERIAL NUMBER REPLY',  (0,),                    tuple([UINT8]*6),       False, 'Returned serial number')
        self._commands.add_command(206, 'GET MODEL NUMBER',         (0,),                    (UINT16,),              False, 'SL_STATUS_T.')
        self._commands.add_command(207, 'GET MODEL NUMBER REPLY',   (0,),                    tuple([UINT8]*12),      False, 'Returned model number.')
        # recieved only commands below vvv 
        self._commands.add_command(208, 'GET SAMPLE RATE',          (0,),                    (UINT16,),              False, 'SL_STATUS_T')
        self._commands.add_command(209, 'GET SAMPLE RATE REPLY',    (0,),                    (UINT8,),               False, 'Returned sample rate, 0 = 1024, 1 = 512, 2 = 256, 3 = 128')
        self._commands.add_command(210, 'SET SAMPLE RATE',          (UINT8,),                   (UINT16,),              False, 'Requires 0,1,2,3 sample rate, returns SL_STATUS_T')
        self._commands.add_command(211, 'PROCEDURE COMPLETE',       (0,),                    (0,),                False, 'A special response that is generated upon a successful write or any remote GATT operation.  Every SET and GET will generate one ')
       # self._commands.add_command(212, 'GET RSSI',               (0,),                    (UINT16,),              False, 'SL_STATUS_T')
       # self._commands.add_command(213, 'GET RSSI REPLY',          (0,),                    (0,),                False, 'The value of RSSI, from -128 to +20')
        self._commands.add_command(214, 'GET FW VERSION',           (0,),                    (UINT16,),              False, 'SL_STATUS_T')
        self._commands.add_command(215, 'GET FW VERSION REPLY',     (0,),                    (UINT8, UINT8, UINT8, UINT8,),   False, 'Firmware version, 1 byte Major, 1 byte Minor, 2 bytes Build')
        # self._commands.add_command(216, 'GET HW INFO',            (0,),                    (UINT16,),              False, 'SL_STATUS_T')      
        self._commands.add_command(218, 'GET HW REV',               (0,),                    (UINT16,),              False, 'SL STATUS_T')
        self._commands.add_command(219, 'GET HW REV REPLY',         (0,),                    (UINT8, UINT8, UINT8, UINT8,),   False, 'Hardware Rev')
        self._commands.add_command(220, 'GET NAME',                 (0,),                    (UINT16,),              False, 'SL_STATUS_T')
        self._commands.add_command(221, 'GET NAME REPLY',           (0,),                    tuple([UINT8]*13),      False, 'The name in characters.')
        self._commands.add_command(222, 'CONNECT BY ADDRESS',       tuple([UINT8]*6),           (UINT16,),              False, 'Requires a BT address to connect to directly, returns SL_STATUS_T ')
        # self._commands.add_command(223, 'SERVICE DISCOVERY',      (0,),                    (UINT16,),              False, 'Returns SL_STATUS_T, and then will start generating characteristic responses.  Those are currently unhandled. Likely this command wont be exposed in the long run ')

        # Holds device type, assigned when device is connected using connect_device()
        self._device_type = None

        # Sample rate index map
        self._sample_rate_index = {
            0: 1024,
            1: 512,
            2: 256,
            3: 128
        }

        # Set device serial number
        self._device_serial_number = device_serial_number

        # Set defaults to most common values
        self._primary_gain = 100
        self._secondary_gain = 26

        # Reboot device
        self.write_read(cmd="RESET")

        # Attempt to connect to device by serial number if provided by the user
        if self._device_serial_number:
            self.connect_to_device(device_serial_number=self._device_serial_number, timeout_sec=scan_timeout_sec)

        def decode_payload(cmd_number: int, payload: bytes) -> tuple:
            if cmd_number == 12:
                """
                Firmware version is stored in the receiver's GATT table, and things
                in the GATT are stored as stings. When we send this data, we read it from
                the GATT and then encode it as POD. As a result of this, when we decode the
                POD we are left with integers that correspond to the ASCII characters of
                the actual values, so we have to further decode the results before sending them.
                """
                major_version: int = int(chr(conv.ascii_bytes_to_int(payload[0:2])))
                minor_version: int = int(chr(conv.ascii_bytes_to_int(payload[2:4])))

                rev_msb: int = conv.ascii_bytes_to_int(payload[4:6])
                rev_lsb: int = conv.ascii_bytes_to_int(payload[6:8])

                rev: int = int(chr(rev_msb) + chr(rev_lsb))

                return (major_version, minor_version, rev)

            return ControlPacket.decode_payload_from_cmd_set(self._commands, cmd_number, payload)

        self._control_packet_factory = partial(ControlPacket, decode_payload)

    
    #------------------------OVERWRITE---------------------------------------------#
    
    def write_read(self, cmd: str|int, payload:int|bytes|tuple[int|bytes]=None, validateChecksum:bool=True) -> Packet:
        """Writes a command with optional payload to POD device, then reads (once) the device response.
        8274D works differently compared to other devices as it is bluetooth based. Some commands require a re-read from the
        Pod Device, in order to get the right payload back. Each Get and Set Command will generate a Procedure Complete (command 211) indicating a successful write/read.


        :param cmd: Command number. 
        :param payload: None when there is no payload. If there \
                is a payload, set to an integer value or a bytes string. Defaults to None.
        :param validateChecksum: Set to True to validate the checksum. Set to False to skip \
                    validation. Defaults to True.

        :return: POD packet beginning with STX and ending with ETX. This may \
                be a standard packet, binary packet, or an unformatted packet (STX+something+ETX). 
                There are some conditions for some commands. For example, if cmd is Local Scan, it returns Payload[1:7]
                because that will be the bluetooth address that can be used to connect to the device.

        :meta private:
        """
        # print(cmd) #NOTE This line is used for testing
        # Flush the port
        self.flush_port()

        self.write_packet(cmd, payload)
        try:
            r = self.read_pod_packet()
        except Exception as e:
            # handle the error (log it and return None)
            print(f"Error reading pod packet: {e}")
            r = None

        if cmd in ['LOCAL SCAN'] and payload == 1:
            max_retries = 3 # Maximum number of retries
            retries = 0 # Times tried
            while retries < max_retries: # Keep trying until limit reached
                if r: # If packet returned
                    if r.command_number == 100:
                        return r
                else:
                    print("No response from device. Waiting for 5 seconds before retrying...")
                    time.sleep(5)  # Wait for 5 seconds

                    try:
                        r = self.read_pod_packet()
                    except Exception as e:
                        # handle the error (log it and return None)
                        print(f"Error reading pod packet: {e}")
                        r = None
                    
                    retries += 1

        if cmd in [
            'CONNECT BY ADDRESS', 
            'GET NAME',
            'SET SAMPLE RATE',
            'GET SAMPLE RATE',
            'SET PERIOD',
            'CONNECT',
            'GET MODEL NUMBER'
            ]:
            read: Packet = self.read_pod_packet()
            if cmd == 'GET NAME':
                read: Packet = self.read_pod_packet()
                return conv.ascii_bytes_to_string(bytes(read.payload))
            if cmd == 'GET SAMPLE RATE':
                return self.get_dict['sample_rate'][0]
            if cmd == 'CONNECT':
                return read
            if cmd == 'GET MODEL NUMBER':
                return conv.ascii_bytes_to_string(bytes(read.payload))
        elif cmd == 'STREAM': #NOTE may not need this
            pass
        return r
    
    def connect_to_device(self, device_serial_number: str, timeout_sec: int|float = 15) -> None:
        """Connect to an 8274 device by name.

        This method scans connected 8274D devices for the provided device name,
        which is automatically prefixed with ``8274-`` before matching. It issues
        a ``DEVICE LIST INFO`` request for each index until the requested device
        is found, then sends a ``CONNECT`` command to establish a connection.

        :param device_name: The device name to connect to. By default, this is
            the device's serial number printed on the device.
        :param timeout_sec: Maximum number of seconds to continue scanning for a
            matching device before raising a :class:`ConnectionError`. Defaults to 15 seconds.

        :raises TypeError: If ``device_name`` is not a string.
        :raises ConnectionError: If the device cannot be found.
        :raises TimeoutError:  if the connection attempt fails
            within the timeout period.
        """

        # Validate type
        if not isinstance(device_serial_number, str):
            raise TypeError(f"device_name must be a string, got {type(device_serial_number).__name__}")
        
        # Reboot device
        self.write_read(cmd="RESET")

        # Start scanning for devices
        self.write_read(cmd="LOCAL SCAN", payload=1)

        # Remove white space on ends and complete device name
        device_serial_number.strip()
        device_serial_number = "8274-" + device_serial_number

        # Start tracking time
        start = time.time()

        # If port exists
        if self._port is not None:

            # Index of slot to scan
            scan_index = 0

            # Stores list of devices found during scan
            found_devices_list = []

            # Loop for time limit
            while time.time() - start < timeout_sec:

                # Get device info for given index slot
                r = self.write_read(cmd="DEVICE LIST INFO", payload=scan_index)

                # If packet returned
                if r:
                    # Parse out device name from packet payload
                    name = self._get_name_from_device_list_info_packet(r)
                    # Skip empty slots
                    if name in (None, "", "UNKNOWN"):
                        continue
                    # Add found device to list
                    found_devices_list.append(name)

                    # Check if device name matches
                    if name == device_serial_number:
                        # Connect to the device
                        r = self.write_read(cmd="CONNECT", payload=scan_index)
                        # Check connection success
                        if r.command_number == 201:
                            # Successful connection
                            # Stop scanning for devices
                            self.write_read(cmd="LOCAL SCAN", payload=0)

                            # Get device type         
                            self._device_type = self.write_read(cmd='GET MODEL NUMBER')

                            # Set gain values based on device type
                            try:
                                self._primary_gain, self._secondary_gain = self.DEVICE_GAINS[self._device_type]
                            except KeyError:
                                raise ConnectionError(
                                    f"Failed to connect to device {device_serial_number}. "
                                    "Unable to get device type"
                                )

                            # exit loop
                            break
                        else:
                            # Failure during connection
                            raise ConnectionError(f"Failed to connect to device {device_serial_number}.")

                # Increment index
                scan_index += 1
            
            else:
                # Time ran out for scan
                # Show troubleshooting tips
                raise TimeoutError(
                    f"Failed to connect to the device '{device_serial_number}' within {timeout_sec} seconds.\n\n"
                    "Troubleshooting:\n"
                    "1. Verify the device serial number is correct and matches exactly.\n"
                    "2. Ensure the battery is installed correctly.\n"
                    "3. If the battery was recently unsealed, allow it to be "
                    "exposed to air for at least 60 seconds before use.\n"
                    "4. If you have many devices powered on, you may need to increase scan_timeout_sec to allow more time for the scan.\n"
                    "5. Move the device closer to the USB dongle and remove "
                    "potential sources of interference.\n"
                    "6. Remove and replace the device battery.\n"
                    "7. Unplug and plug back in USB dongle.\n"
                    f"List of devices found during scan: {found_devices_list}"
                )

    # Fixed size of 8274D binary data packet, see docs for diagram of packet
    _STREAMING_PACKET_LEN = 259

    def _get_name_from_device_list_info_packet(self, packet: Packet) -> str:
        """
        Extract device name from packet payload.

        :param packet: The packet returned from the command 'DEVICE LIST INFO'.
        
        :return: String containing the name of the device.

        :meta private:
        """
        return conv.ascii_bytes_to_string(bytes(packet.payload[8:24]))
    
    def read_pod_packet_streaming(self, timeout_sec: float = 1.0, validate_checksum: bool = False):
        """Continuously reads POD packets and filters for valid data or control packets.
        
        This method reads from the device in a loop, returning the first valid packet encountered.
        Control packets are returned immediately. For data packets, attempts to parse them as 
        DataPacket8274D objects. Invalid data packets are discarded and reading continues until 
        a valid packet is obtained.
        
        :param timeout_sec: Timeout in seconds for each read operation. Defaults to 5.0 seconds.
        :param validate_checksum: Set to True to validate packet checksums. Set to False to skip \
                checksum validation. Defaults to True.
        
        :return: Either a ControlPacket or a DataPacket8274D object, depending on what is received \
                from the device.
        
        :raises TypeError: If the port has not been initialized (self._port is None).
        
        :meta private:
        """
        if self._port is None:
            raise TypeError("PortIO object does not exist!")
        while True:
            packet = self.read_pod_packet(validate_checksum=validate_checksum, timeout_sec=timeout_sec)         
            packet: Packet = self.read_pod_packet(validate_checksum=validate_checksum)
            if isinstance(packet, ControlPacket):
                return packet
            raw_packet = packet.raw_packet if hasattr(packet, "raw_packet") else packet
            try:
                return DataPacket8274D(raw_packet=raw_packet, primary_gain=self._primary_gain, secondary_gain=self._secondary_gain)
            except TypeError:
                # Not a valid 8274D data packet; ignore and keep reading.
                continue

    @property
    def sample_rate(self) -> int:
        """Currently set sample rate."""
        if self._sample_rate is None:
            self.write_packet("GET SAMPLE RATE")
            r1 = self.read_pod_packet() # Returns the packet for the command
            r2 = self.read_pod_packet() # Returns the packet contianing the sample rate index value
            sample_rate_index = r2.payload[0]
            self._sample_rate = self._sample_rate_index[sample_rate_index]
        return self._sample_rate
    
    @sample_rate.setter
    def sample_rate(self, rate: int) -> None:
        key = next((k for k, v in self._sample_rate_index.items() if v == rate), None)
        if key is None:
            raise ValueError(f'Sample rate {rate} not valid. Please use one of the following valid sample rates: {list(self._sample_rate_index.values())}')
        self.write_read('SET SAMPLE RATE', key)
        self._sample_rate: int = rate

    def get_dict(self):
        d = {
            'port': self.port,
            'baudrate': self.baudrate,
            'device_name': self.device_name,
        }
        if self._sample_rate is not None:
            d['sample_rate'] = self._sample_rate
        if self._device_serial_number is not None:
            d['device_serial_number'] = self._device_serial_number
        return d
