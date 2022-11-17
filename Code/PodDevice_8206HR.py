from BasicPodProtocol import POD_Basics
from PodCommands import POD_Commands

class POD_8206HR(POD_Basics) : 

    # ============ GLOBAL CONSTANTS ============    ========================================================================================================================

    # ============ DUNDER METHODS ============      ========================================================================================================================

    def __init__(self, port, baudrate=9600) :
        # initialize POD_Basics
        super().__init__(port, baudrate=baudrate) 
        # get constants for adding commands 
        U8  = POD_Commands.U8()
        U16 = POD_Commands.U16()
        # remove unimplemented commands 
        self._commands.RemoveCommand(5)  # STATUS
        self._commands.RemoveCommand(9)  # ID
        self._commands.RemoveCommand(10) # SAMPLE RATE
        self._commands.RemoveCommand(11) # BINARY
        # add device specific commands
        self._commands.AddCommand(100, 'GET SAMPLE RATE',      0,       U16      )
        self._commands.AddCommand(101, 'SET SAMPLE RATE',      U16,     0        )
        self._commands.AddCommand(102, 'GET LOWPASS',          U8,      U16      )
        self._commands.AddCommand(103, 'SET LOWPASS',          U8+U16,  0        )
        self._commands.AddCommand(104, 'SET TTL OUT',          U8+U8,   0        )
        self._commands.AddCommand(105, 'GET TTL IN',           U8,      U8       )
        self._commands.AddCommand(106, 'GET TTL PORT',         0,       U8       )
        self._commands.AddCommand(107, 'GET FILTER CONFIG',    0,       U8       )
        self._commands.AddCommand(180, 'BINARY4 DATA ',        0,       16       )     # see ReadPODpacket_Binary()

    # ============ STATIC METHODS ============      ========================================================================================================================

    @staticmethod
    def UnpackPODpacket_Binary(msg) : 
        # Binary 4 format = 
        #   STX (1 byte) + command (4 bytes) + packet number (1 bytes) + TTL (1 byte) 
        #   + ch0 (2 bytes) + ch1 (2 bytes) + ch2 (2 bytes) + checksum (2 bytes) + ETX (1 byte)
        MINBYTES=16

        # get number of bytes in message
        packetBytes = len(msg)

        # message must have enough bytes, start with STX, or end with ETX
        if(    (packetBytes != MINBYTES)
            or (msg[0].to_bytes(1,'big') != POD_Basics.STX()) 
            or (msg[packetBytes-1].to_bytes(1,'big') != POD_Basics.ETX())
        ) : 
            raise Exception('Cannot unpack an invalid POD packet.')

        # create dict and separate message parts
        msg_unpacked = {
            'Command Number'    : msg[1:5],
            'Packet #'          : msg[5].to_bytes(1,'big'),
            'TTL'               : msg[6].to_bytes(1,'big'),
            'Ch0'               : msg[7:9],
            'Ch1'               : msg[9:11],
            'Ch2'               : msg[11:13],
            'Checksum'          : msg[13:15]
        }
        
        # return unpacked POD command
        return(msg_unpacked)

    # ============ PUBLIC METHODS ============      ========================================================================================================================

    def ReadPODpacket_Binary(self, validateChecksum=True) :
        """
        Binary 4 Data Format
        ------------------------------------------------------------		
        Byte    Index	        Value	
        ------------------------------------------------------------		
        0	    0x02	        Binary		STX
        1	    0	            ASCII		Command Number Byte 0
        2	    0	            ASCII		Command Number Byte 1
        3	    B	            ASCII		Command Number Byte 2
        4	    4	            ASCII		Command Number Byte 3
        5	    Packet Number 	Binary		A rolling value that increases with each packet, and rolls over to 0 after it hits 255
        6	    TTL	            Binary		The byte value of the TTL port.  Value would be equivalent to the command 106 GET TTL PORT above
        7	    Ch0 LSB	        Binary		Least significant byte of the Channel 0 (EEG1) value
        8	    Ch0 MSB	        Binary		Most significant byte of the Channel 0 (EEG1) value
        9	    Ch1 LSB	        Binary		Channel 1 / EEG2 LSB
        10	    Ch1 MSB	        Binary		Channel 1 / EEG2 MSB
        11	    Ch2 LSB	        Binary		Channel 2 / EEG3/EMG LSB
        12	    Ch2 MSB	        Binary		Channel 2 / EEG3/EMG MSB
        13	    Checksum MSB	ASCII		MSB of checksum
        14	    Checksum LSB	ASCII		LSB of checkxum
        15	    0x03	        Binary		ETX
        ------------------------------------------------------------
        """

        # read until STX found
        packet = None
        while(packet != self.STX()) :
            packet = self._port.Read(1)     # read next byte  

        # read remaining 15 bytes
        packet += self._port.Read(15)

        # verify that Last is ETX
        last = packet[len(packet)-1].to_bytes(1,'big')
        if(last != self.ETX()) : 
            raise Exception('Bad binary read.')
        
        if(validateChecksum) :
            # raise exception if chacksum is invalid
            if(POD_Basics.ValidateChecksum(packet) == False ):
                raise Exception('Bit error in recieved POD message.')

        # return full binary packet
        return(packet)