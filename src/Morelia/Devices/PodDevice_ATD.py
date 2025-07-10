# local imports 
from Morelia.Devices import AcquisitionDevice, Pod

# authorship
__author__      = "Mackenzie Meier"
__maintainer__  = "Mackenzie Meier"
__credits__     = ["Mackenzie Meier", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2025, Mackenzie Meier"
__email__       = "sales@pinnaclet.com"

class PodATD(AcquisitionDevice) :
    """
    POD_8206HRTest handles communication using an 8206HR Testing Pod device

    Attributes:

    """

    # ------------ DUNDER ------------           ------------------------------------------------------------------------------------------------------------------------

    def __init__(self, port: str|int, baudrate:int=9600, device_name: str | None =  None) -> None :
        """Runs when an instance is constructed. It runs the parent's initialization. Then it updates \
        the _commands to contain the appropriate commands for an 8206-HR Test POD device. 

        Args:
            port (str | int): Serial port to be opened. Used when initializing the COM_io instance.
            baudrate (int, optional): Integer baud rate of the opened serial port. Used when initializing \
                the COM_io instance. Defaults to 9600.

        """

        # initialize POD Basics
        super().__init__(port, 2000, baudrate, device_name) 
        # get constants for adding commands
        U8 = Pod.get_u(8)
        U16 = Pod.get_u(16)
        B4  = 8
        self._commands.remove_command(5)  # STATUS
        self._commands.remove_command(9)  # ID
        self._commands.remove_command(10) # SAMPLE RATE
        self._commands.remove_command(11) # BINARY

        # add device specific commands
        self._commands.add_command(100, 'GET CHANNEL CONFIG', (U8,),          (U8,),  False,  'Gets the mode of the selected channel')
        self._commands.add_command(101, 'SET CHANNEL CONFIG', (U8, U8, U16,), (0,),   False,  'Sets the channel mode and amplitude')
        self._commands.add_command(102, 'GET FREQ',          (0,),           (U16,), False,  'Sets the system waveform frequency ')
        self._commands.add_command(103, 'SET FREQ',          (U16,),         (0,),   False,  'Gets the system waveform frequency ')
        self._commands.add_command(104, 'GET DIGITAL IO',    (U8,),          (U8,),  False,  'Gets the value of the digital pin')
        self._commands.add_command(105, 'SET DIGITAL IO',    (U8,U8,),       (0,),   False,  'Sets the value of the digital pin')
        self._commands.add_command(106, 'GET ANALOG',        (U8,),          (0,),   False,  'Gets an analog input' )

    # ------------ OVERWRITE ------------           ------------------------------------------------------------------------------------------------------------------------


    # def ReadPODpacket(self, validateChecksum: bool = True, timeout_sec: int | float = 5) -> Packet:
    #     """Reads a complete POD packet, either in standard or binary format, beginning with STX and \
    #     ending with ETX. Reads first STX and then starts recursion. 

    #     Args:
    #         validateChecksum (bool, optional): Set to True to validate the checksum. Set to False to \
    #             skip validation. Defaults to True.
    #         timeout_sec (int|float, optional): Time in seconds to wait for serial data. \
    #             Defaults to 5. 

    #     Returns:
    #         Packet: POD packet beginning with STX and ending with ETX. This may be a \
    #             standard packet, binary packet, or an unformatted packet (STX+something+ETX). 
    #     """
    #     packet: Packet = super().ReadPODpacket(validateChecksum, timeout_sec)
    #     # check for special packets
    #     #if(isinstance(packet, PacketStandard)) : 
    #         #if(packet.CommandNumber() == 106) : # 106, 'GET TTL PORT'
    #             #packet.SetCustomPayload(self._TranslateTTLbyte_ASCII, (packet.payload,))
    #     # return packet
    #     return packet

    
