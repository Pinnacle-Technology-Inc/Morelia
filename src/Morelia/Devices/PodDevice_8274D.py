# local imports 
import time
from Morelia.Devices import Pod, AcquisitionDevice

from Morelia.packet.legacy import PacketBinary, Packet

from Morelia.packet import ControlPacket
import Morelia.packet.conversion as conv

from functools import partial

# authorship
__author__      = "Sree Kondi"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Sree Kondi", "Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Pod8274D(AcquisitionDevice) : 
    """POD_8274D handles communication using an 8274D POD device. Currently under construction and is unreliable.

    :param port: Serial port to be opened. Used when initializing the COM_io instance.
    :param baudrate: Baud rate of the opened serial port. Default value is 9600.
    :param device_name: Virtual name used to indentify device.
    """


    def __init__(self, port: str|int, baudrate:int=921600, device_name: str | None = None) -> None :
        """Runs when an instance is constructed. It runs the parent's initialization. Then it updates \
        the _commands to contain the appropriate command set for an 8274 POD device. 
        """
        # initialize POD_Basics
        super().__init__(port, 1024, baudrate=baudrate, device_name=device_name, get_sample_rate_cmd_no=208, set_sample_rate_cmd_no=210) 
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
        #self._commands.add_command(208, 'GET SAMPLE RATE',          (0,),                    (UINT16,),              False, 'SL_STATUS_T')
        self._commands.add_command(209, 'GET SAMPLE RATE REPLY',    (0,),                    (UINT8,),               False, 'Returned sample rate, 0 = 1024, 1 = 512, 2 = 256, 3 = 128')
        #self._commands.add_command(210, 'SET SAMPLE RATE',          (UINT8,),                   (UINT16,),              False, 'Requires 0,1,2,3 sample rate, returns SL_STATUS_T')
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
        #print(cmd)
        self.write_packet(cmd, payload)
        r = self.read_pod_packet()
        if cmd in ['LOCAL SCAN'] :
            max_retries = 3  # Maximum number of retries
            retries = 0
            while retries < max_retries:
                r = self.read_pod_packet()
                if not r:
                    print("No response from device. Waiting for 5 seconds before retrying...")
                    time.sleep(5)  # Wait for 5 seconds
                    retries += 1
                    continue
                if r.command_number == 101 and len(r.payload) > 1:
                    return r  
        if cmd in ['CONNECT BY ADDRESS', 'GET NAME', 'SET SAMPLE RATE', 'GET SAMPLE RATE', 'SET PERIOD']:
            read: Packet = self.read_pod_packet()
            if cmd == 'GET NAME':
                read: Packet = self.read_pod_packet()
                name = read.payload
                return name
            if cmd == 'GET SAMPLE RATE':
                read.payload[0]
                return data['Payload'][0]
        elif cmd == 'STREAM':
            while True:
                x = self.read_pod_packet(validateChecksum)
                data: dict = x.TranslateAll()
        return r
