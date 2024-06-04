# local imports 
import time
from Morelia.Devices import Pod
from Morelia.Packets import Packet, PacketStandard, PacketBinary

# authorship
__author__      = "Sree Kondi"
__maintainer__  = "Sree Kondi"
__credits__     = ["Sree Kondi", "Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Pod8274D(Pod) : 
    """POD_8274D handles communication using an 8274D POD device.
    """

    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self, port: str|int, baudrate:int=921600) -> None :
        """Runs when an instance is constructed. It runs the parent's initialization. Then it updates \
        the _commands to contain the appropriate command set for an 8274 POD device. 

        Args:
            port (str | int): Serial port to be opened. Used when initializing the COM_io instance.
            baudrate (int, optional): Integer baud rate of the opened serial port. Used when initializing \
                the COM_io instance. Defaults to 921600.
        """
        # initialize POD_Basics
        super().__init__(port, baudrate=baudrate) 
        # get constants for adding commands 
        U8  = Pod.GetU(8)
        U16 = Pod.GetU(16)
        U32 = Pod.GetU(32)
        NOVALUE = Pod.GetU(0)
        # add device specific commands
        self._commands.AddCommand(100, 'LOCAL SCAN',               (U8,),                   (U16,),              False, 'Enables or disables scan.  1 enables, 0 disables.  Returns SL_STATUS_T status code, 0x0000 is success, all others are error codes.')
        self._commands.AddCommand(101, 'DEVICE LIST INFO',         (U8,),                   tuple([U8]*24),      False, 'Information string about a scanned device - includes advertising index, bluetooth address, and device name.')
        self._commands.AddCommand(102, 'LOCAL CONNECTION INFO',    (U8,),                   tuple([U8]*24),      False, 'Information string about a connected device - includes connection index, bluetooth address, and device name.')
        self._commands.AddCommand(103, 'LOCAL CONNECTION STATUS',  (0,),                    (U8,),               False, 'Returns a bitmask indicating which connection slots are occupied.  0 = unused, 1 = connected.  Only bits 0-3 are relevant.')
        self._commands.AddCommand(104, 'DISCONNECT ALL',           (0,),                    (U8,),               False, 'Attempts to disconnect all connections.  Returns a bitmask indicating which connections have been removed.  0=unchanged, 1=disconnected.  Only bits 0-3 are relevant.')
        self._commands.AddCommand(105, 'SET BAUD RATE',            (U8,),                   (U8,),               False, 'Sets the local baud rate of the device.  Sends a reponse packet with the requested value before changing rates.  0 = 115200, 1 = 460800, 2=921600.  ')
        self._commands.AddCommand(106, 'CHANNEL SCAN',             (U8,),                   tuple([U8]*5),       False, 'Enables the bluetooth channel scan.  0 = disable, 1 = enable.  After enabling, periodic packets of this type will be sent back with a 5 byte payload of channel availability data,  bits 0-36, 1 = available and 0 = unavailable.')
        # self._commands.AddCommand(128, 'GET WAVEFORM',           (0,),                    (U16,),              False, 'Requests to read the stored FSCV waveform from the remote device.  Reply is SL_STATUS_T status code; 0x0000 is success, all others are error codes.')
        # self._commands.AddCommand(129, 'GET WAVEFORM REPLY',     (0,),                    (NOVALUE,),          False, 'The waveform descriptor returned from the remote device.  Variable length.')
        # self._commands.AddCommand(130, 'SET WAVEFORM',           (NOVALUE,),              (U16,),              False, 'Sends the waveform to the remove device.  Reply is SL_STATUS_T.')
        self._commands.AddCommand(131, 'GET PERIOD',               (0,),                    (U16,),              False, 'Requests the FSCV sample period.  Reply is SL_STATUS_T.')
        self._commands.AddCommand(132, 'GET PERIOD REPLY',         (0,),                    (U16,),              False, 'The period returned from the remote device in 1/32,758ths of a second.')
        self._commands.AddCommand(133, 'SET PERIOD',               (U16,),                  (0,),                False, 'Sends the period to the remote device.  Reply is SL_STATUS_T')
        # self._commands.AddCommand(134, 'GET STIMULUS',           (0,),                    (U16,),              False, 'Requests to read the stimulus config from the remote device.  Reply is SL_STATUS_T')
        # self._commands.AddCommand(135, 'GET STIMULUS REPLY',     (0,),                    (NOVALUE,),          False, 'Sends the period to the remote device.  Reply is SL_STATUS_T')
        # self._commands.AddCommand(136, 'SET STIMULUS',           (U32, U32, U32, U32,),   (0,),                False, 'Sends a  stimulus command to the remote device.  This will initiate the requested stimulus at the next waveform start.  See below for details.')
        self._commands.AddCommand(200, 'CONNECT',                  (U8,),                   (U16,),              False, 'Requests a connection to the given advertising slot.  Returns connection status. ')
        self._commands.AddCommand(201, 'CONNECT REPLY',            (0,),                    (0,),                False, 'Indicates a connection completed successfully.')
        self._commands.AddCommand(202, 'DISCONNECT',               (U8,),                   (U16,),              False, 'Requests to disconnect from a given connection slot.  Returns a disconnect status.')
        self._commands.AddCommand(203, 'DISCONNECT REPLY',         (0,),                    (0,),                False, 'Indicates the disconnect completed successfully')
        self._commands.AddCommand(204, 'GET SERIAL NUMBER',        (0,),                    (U16,),              False, 'Requests a read - returns SL_STATUS_T value.  0x0000 is success, all others are error codes.')
        self._commands.AddCommand(205, 'GET SERIAL NUMBER REPLY',  (0,),                    tuple([U8]*6),       False, 'Returned serial number')
        self._commands.AddCommand(206, 'GET MODEL NUMBER',         (0,),                    (U16,),              False, 'SL_STATUS_T.')
        self._commands.AddCommand(207, 'GET MODEL NUMBER REPLY',   (0,),                    tuple([U8]*12),      False, 'Returned model number.')
        # recieved only commands below vvv 
        self._commands.AddCommand(208, 'GET SAMPLE RATE',          (0,),                    (U16,),              False, 'SL_STATUS_T')
        self._commands.AddCommand(209, 'GET SAMPLE RATE REPLY',    (0,),                    (U8,),               False, 'Returned sample rate, 0 = 1024, 1 = 512, 2 = 256, 3 = 128')
        self._commands.AddCommand(210, 'SET SAMPLE RATE',          (U8,),                   (U16,),              False, 'Requires 0,1,2,3 sample rate, returns SL_STATUS_T')
        self._commands.AddCommand(211, 'PROCEDURE COMPLETE',       (0,),                    (0,),                False, 'A special response that is generated upon a successful write or any remote GATT operation.  Every SET and GET will generate one ')
       # self._commands.AddCommand(212, 'GET RSSI',               (0,),                    (U16,),              False, 'SL_STATUS_T')
       # self._commands.AddCommand(213, 'GET RSSI REPLY',          (0,),                    (0,),                False, 'The value of RSSI, from -128 to +20')
        self._commands.AddCommand(214, 'GET FW VERSION',           (0,),                    (U16,),              False, 'SL_STATUS_T')
        self._commands.AddCommand(215, 'GET FW VERSION REPLY',     (0,),                    (U8, U8, U8, U8,),   False, 'Firmware version, 1 byte Major, 1 byte Minor, 2 bytes Build')
        # self._commands.AddCommand(216, 'GET HW INFO',            (0,),                    (U16,),              False, 'SL_STATUS_T')      
        self._commands.AddCommand(218, 'GET HW REV',               (0,),                    (U16,),              False, 'SL STATUS_T')
        self._commands.AddCommand(219, 'GET HW REV REPLY',         (0,),                    (U8, U8, U8, U8,),   False, 'Hardware Rev')
        self._commands.AddCommand(220, 'GET NAME',                 (0,),                    (U16,),              False, 'SL_STATUS_T')
        self._commands.AddCommand(221, 'GET NAME REPLY',           (0,),                    tuple([U8]*13),      False, 'The name in characters.')
        self._commands.AddCommand(222, 'CONNECT BY ADDRESS',       tuple([U8]*6),           (U16,),              False, 'Requires a BT address to connect to directly, returns SL_STATUS_T ')
        # self._commands.AddCommand(223, 'SERVICE DISCOVERY',      (0,),                    (U16,),              False, 'Returns SL_STATUS_T, and then will start generating characteristic responses.  Those are currently unhandled. Likely this command wont be exposed in the long run ')
    
    #------------------------OVERWRITE---------------------------------------------#
    
    def WriteRead(self, cmd: str|int, payload:int|bytes|tuple[int|bytes]=None, validateChecksum:bool=True) -> Packet:
        """Writes a command with optional payload to POD device, then reads (once) the device response.
        8274D works differently compared to other devices as it is bluetooth based. Some commands require a re-read from the
        Pod Device, in order to get the right payload back. Each Get and Set Command will generate a Procedure Complete (command 211) indicating a successful write/read.

        Args:
            cmd (str | int): Command number. 
            payload (int | bytes | tuple[int|bytes], optional): None when there is no payload. If there \
                is a payload, set to an integer value or a bytes string. Defaults to None.
            validateChecksum (bool, optional): Set to True to validate the checksum. Set to False to skip \
                    validation. Defaults to True.

        Returns:
            Packet: POD packet beginning with STX and ending with ETX. This may \
                be a standard packet, binary packet, or an unformatted packet (STX+something+ETX). 
                There are some conditions for some commands. For example, if cmd is Local Scan, it returns Payload[1:7]
                because that will be the bluetooth address that can be used to connect to the device.
        """
        print(cmd)
        self.WritePacket(cmd, payload)
        r = self.ReadPODpacket()
        data: dict = r.TranslateAll()
        print("read1:", data)
        if cmd in ['LOCAL SCAN'] :
            max_retries = 3  # Maximum number of retries
            retries = 0
            while retries < max_retries:
                r = self.ReadPODpacket()
                if not r:
                    print("No response from device. Waiting for 5 seconds before retrying...")
                    time.sleep(5)  # Wait for 5 seconds
                    retries += 1
                    continue
                data: dict = r.TranslateAll()
                print("read:", data)
                if data['Command Number'] == 101 and len(data['Payload']) > 1:
                    return data['Payload'][1:7]  # Assuming the payload contains the address to connect
        if cmd in ['CONNECT BY ADDRESS', 'GET NAME', 'SET SAMPLE RATE', 'GET SAMPLE RATE', 'SET PERIOD']:
            read: Packet = self.ReadPODpacket()
            data: dict = read.TranslateAll()
            print("read3:", data)
            if cmd == 'GET NAME':
                read: Packet = self.ReadPODpacket()
                data: dict = read.TranslateAll()
                name = data['Payload']
                print("read3:", data)
                return name
            if cmd == 'GET SAMPLE RATE':
                return data['Payload'][0]
        elif cmd == 'STREAM':
            while True:
                x = self.ReadPODpacket(validateChecksum)
                data: dict = x.TranslateAll()
        return r
