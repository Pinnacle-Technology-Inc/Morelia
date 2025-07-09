# local imports
from Morelia.Devices.SerialPorts import PortIO, FindPorts
from Morelia.Commands import CommandSet
from Morelia.packet import ControlPacket, PodPacket
from Morelia.packet.data import DataPacket
from Morelia.exceptions import InvalidChecksumError
import Morelia.packet.conversion as conv

from functools import partial

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Pod : 
    """
    Pod handles basic communication with a generic POD device, including reading and writing 
    packets and packet interpretation. This is the parent class for any device that communcates using the POD protocol.
    
    :param port: Serial port to be opened. Used when initializing the COM_io instance.
    :param baudrate: Baud rate of the opened serial port. Default value is 9600.
    :param device_name: Virtual Name used to indentify device.
    """
    

    def __init__(self, port: str|int,  baudrate:int=9600, device_name: str | None = None) -> None : 
        """Runs when an instance of Pod is constructed. It initializes the instance variable for 
        the serial port communication (_port) and for the command handler (_commands).
        """

        # initialize serial port 
        self._port : PortIO = PortIO(port, baudrate)

        # create object to handle commands 
        self._commands : CommandSet = CommandSet()
       
        #set device name.
        self._device_name: str = device_name if device_name else str(port)
    
        #function that will be used to create new control packets from this device.
        #essentially, this is a curried (partially applied) version of the constructor for ControlPacket.
        #if unfamiliar with partially applied functions, see here: https://docs.python.org/3/library/functools.html#functools.partial
        self._control_packet_factory = partial(ControlPacket, self._commands)


    @staticmethod
    def get_u(u: int) -> int : 
        """Number of hexadecimal characters for an unsigned u-bit value.

        :param u: 8, 16, or 32 bits. Enter any other number for NO_VALUE.

        :return: number of hexadecimal characters for an unsigned u-bit value.
        """
        match u : 
            case  8: return(CommandSet.get_uint8())
            case 16: return(CommandSet.get_uint16())
            case 32: return(CommandSet.get_uint32())
            case  _: return(CommandSet.no_value())

    @property
    def device_name(self) -> str:
        """The virtual device name."""
        return self._device_name

    @staticmethod
    def choose_port(forbidden:list[str]=[]) -> str : 
        """Checks user's Operating System, and chooses ports accordingly.

        :param forbidden: List of port names that are already used. Defaults to an empty list.

        :return: Name of the port.
        """
        return FindPorts.choose_port(forbidden)

    # ------------ CHECKSUM HANDLING ------------   ------------------------------------------------------------------------------------------------------------------------


    @staticmethod
    def _validate_checksum(msg: bytes) -> bool :
        """Validates the checksum of a given POD packet. The checksum is valid if the calculated checksum 
        from the data matches the checksum written in the packet. 

        :param msg: Bytes message containing a POD packet: STX (1 bytes) + data (? bytes) + checksum (2 bytes) + ETX (1 byte). 

        :return: True if the checksum is correct, false otherwise.

        :raises Exception: msg does not begin with STX or end with ETX. 

        :meta private:
        """
        # ... assume that msg contains STX + packet + csm + ETX. This assumption is good for more all 
        #     pod packets except variable length binary packet
        # get length of POD packet 
        packet_bytes = len(msg)
        # check that packet begins with STX and ends with ETX
        if(    (msg[0].to_bytes(1,'big') != PodPacket.STX) 
            or (msg[packet_bytes-1].to_bytes(1,'big') != PodPacket.ETX)
        ) : 
            raise InvalidChecksumError('Cannot calculate the checksum of an invalid POD packet. The packet must begin with STX and end with ETX.')
        # get message contents excluding STX/ETX
        msg_packet = msg[1:packet_bytes-3]
        msg_csm = msg[packet_bytes-3:packet_bytes-1]
        # calculate checksum from content packet  
        csm_valid = Pod.checksum(msg_packet)
        # return True if checksums match 
        if(msg_csm == csm_valid) :
            return(True)
        else:
            return(False)



    @staticmethod
    def checksum(bytes_in: bytes) -> bytes:
        """Calculates the checksum of a given bytes message. This is achieved by summing each byte in the 
        message, inverting, and taking the last byte.

        :param bytes_in: Bytes message containing POD packet data.

        :return: Two ASCII-encoded bytes containing the checksum for ``bytes_in``.
        """
        # sum together all bytes in byteArr
        sum = 0
        for b in bytes_in : 
            sum = sum + b
        # invert and get last byte 
        cs  = ~sum & 0xFF
        # convert int into bytes 
        cs_bytes = conv.int_to_ascii_bytes(cs, 2)
        # return checksum bytes
        return(cs_bytes)


    @staticmethod
    def build_pod_packet_standard(command_number: int, payload:bytes|None=None) -> bytes : 
        """Builds a standard POD packet (control packet) as bytes: STX (1 byte) + command number (4 bytes) \
        + optional packet (? bytes) + checksum (2 bytes)+ ETX (1 bytes).

        :param command_number: Integer representing the command number. This will be converted into a \
        4 byte long ASCII-encoded bytes string.
        :param payload: bytes string containing the payload. Defaults to None.

        :return: Bytes string of a complete standard POD packet.
        """
        # prepare components of packet
        stx = PodPacket.STX                              # STX indicating start of packet (1 byte)
        cmd = conv.int_to_ascii_bytes(command_number, 4)  # command number (4 bytes)
        etx = PodPacket.ETX                              # ETX indicating end of packet (1 byte)
        # build packet with payload 
        if(payload) :
            csm = Pod.checksum(cmd+payload)         # checksum (2 bytes)
            packet = stx + cmd + payload + csm + etx        # pod packet with payload (8 + payload bytes)
        # build packet with NO payload 
        else :
            csm = Pod.checksum(cmd)                 # checksum (2 bytes)
            packet = stx + cmd + csm + etx                  # pod packet (8 bytes)
        # return complete bytes packet
        return(packet)

    
    @staticmethod
    def payload_to_bytes(payload: int|bytes|tuple[int|bytes], arg_sizes: tuple[int]) -> bytes :
        """Converts a payload into a bytes string (assuming that the payload is for a valid command).

            :param payload: Integer, bytes, or tuple containing the payload.
            :param arg_sizes: Tuple of the argument sizes.

            :return: Bytes string of the payload.
        """
        # if integer payload is given ... 
        if(isinstance(payload,int)):
            # convert to bytes of the expected length 
            pld = conv.int_to_ascii_bytes(payload,sum(arg_sizes))
        # if bytes payload is given...
        elif(isinstance(payload, bytes)):
            pld = payload
        # if tuple payload is given...
        else: 
            # build list of bytes payload parts 
            temp_pld = [None]*len(payload)
            for i in range(len(payload)) : 
                if(isinstance(payload[i], int)) :
                    # convert to bytes of the expected length 
                    temp_pld[i] = conv.int_to_ascii_bytes(payload[i],arg_sizes[i])
                else : 
                    # accept bytes payload as given
                    temp_pld[i] = payload[i]
            # concatenate list items
            pld = temp_pld[0]
            for i in range(len(temp_pld)-1):
                pld += temp_pld[i+1]
        # return payload as bytes
        return(pld)
            
    

    def flush_port(self) -> bool : 
        """Reset the input and output serial port buffer.

        :return: True of the buffers are flushed, False otherwise.
        """
        return(self._port.flush())
    
    
    def set_baudrate_of_device(self, baudrate: int) -> bool : 
        """If the port is open, it will change the baud rate to the parameter's value.

        :param baudrate: Baud rate to set for the open serial port. 

        :return: True if successful at setting the baud rate, false otherwise.
        """
        # set baudrate of the open COM port. Returns true if successful.
        return(self._port.set_baudrate(baudrate))


    def get_device_commands(self) -> dict[int, list[str|tuple[int]|bool]]:
        """Gets the dictionary containing the class instance's available POD commands.

        :return: Dictionary containing the available commands and their \
                information.Formatted as key(command number) : value([command name, number of argument \
                ASCII bytes, number of return bytes, binary flag ])
        """
        # Get commands from this instance's command dict object 
        return(self._commands.GetCommands())
    
    def test_connection(self, ping_cmd:str|int='PING') -> bool :
        """Tests if a POD device can be read from or written. Sends a PING command. 

        :param ping_cmd: Command name or number to ping. Defaults to 'PING'.

        :return: True for successful connection, false otherwise.
            
        """
        if(not self._commands.does_command_exist(ping_cmd)) : 
            raise Exception('[!] Ping command \''+str(ping_cmd)+'\' does not exist for this POD device.')
        # returns True when connection is successful, false otherwise
        try:
            self.flush_port() # clear out any unread packets 
            w: ControlPacket = self.write_packet(cmd=ping_cmd)
            r: PodPacket = self.read_pod_packet()
        except:   return(False)
        # check that read matches ping write
        if(w ==r ): return(True)
        return(False)
    

    def get_pod_packet(self, cmd: str|int, payload:int|bytes|tuple[int|bytes]=None) -> bytes :
        """Builds a POD packet and writes it to a POD device via COM port. If an integer payload is give, \
        the method will convert it into a bytes string of the length expected by the command. If a bytes \
        payload is given, it must be the correct length. 

        :param cmd: Command number. 
        :param payload: None when there is no payload. If there is a payload, set to an integer value, bytes string, or tuple. Defaults to None.

        :return: Bytes string of the POD packet. 
        """
        # return False if command is not valid
        if(not self._commands.does_command_exist(cmd)) : 
            raise Exception('POD command does not exist.')
        # get command number 
        if(isinstance(cmd,str)):
            cmd_num : int = self._commands.command_number_from_name(cmd)
        else: 
            cmd_num : int = cmd
        # get length of expected paylaod 
        arg_sizes = self._commands.argument_hex_char(cmd_num)
        # check if command requires a payload
        if( sum(arg_sizes) > 0 ): 
            # raise exception if command is invalid
            self._commands.validate_command(cmd_num, payload)
            # get payload in bytes
            pld = Pod.payload_to_bytes(payload, arg_sizes)
        else :
            pld = None
        # build POD packet 
        packet = Pod.build_pod_packet_standard(cmd_num, payload=pld)
        # return complete packet 
        return(packet)
    
    def write_read(self, cmd: str|int, payload:int|bytes|tuple[int|bytes]=None, validate_checksum:bool=True, timeout_sec: int|float = 5) -> PodPacket :
        """Writes a command with optional payload to POD device, then reads (once) the device response.

        :param cmd: Command number. 
        :param payload: None when there is no payload. If there is a payload, set to an integer value or a bytes string. Defaults to None.
        :param validate_checksum: Set to True to validate the checksum. Set to False to skip validation. Defaults to True.

        :return: POD packet beginning with STX and ending with ETX. This may \
                be a control packet, data packet, or an unformatted packet (STX+something+ETX). 
        """
        self.write_packet(cmd, payload)
        r = self.read_pod_packet(validate_checksum, timeout_sec)
        return(r)


    def write_packet(self, cmd: str|int, payload:int|bytes|tuple[int|bytes]=None) -> ControlPacket:
        """Builds a POD packet and writes it to the POD device. 

        :param cmd: Command number.
        :param payload: None when there is no payload. If there is a payload, set to an integer value, bytes string, or tuple. Defaults to None.

        :return: Packet that was written to the POD device.
        """
        # POD packet 
        packet = self.get_pod_packet(cmd, payload)
        # write packet to serial port 
        self._port.write(packet)
        # returns packet that was written
        return ControlPacket(self._commands, packet)


    def read_pod_packet(self, validate_checksum:bool=True, timeout_sec: int|float = 5) -> PodPacket :
        """Reads a complete POD packet, either in standard or binary format, beginning with STX and \
        ending with ETX. Reads first STX and then starts recursion. 

        :param validate_checksum: Set to True to validate the checksum. Set to False to skip validation. Defaults to True.
        :param timeout_sec: Time in seconds to wait for serial data. Defaults to 5. 

        :return: POD packet beginning with STX and ending with ETX. This may be a \
        control packet, data packet, or an unformatted packet (STX+something+ETX). 
        """
        # read until STX is found
        b = None
        while(b != PodPacket.STX) :
            b = self._port.read(1,timeout_sec)     # read next byte  
        # continue reading packet  
        packet = self._read_pod_packet_recursive(validate_checksum=validate_checksum)
        # return final packet
        return(packet)


    def _read_pod_packet_recursive(self, validate_checksum:bool=True) -> PodPacket : 
        """Reads the command number. If the command number ends in ETX, the packet is returned. \
        Next, it checks if the command is allowed. Then, it checks if the command is standard or \
        binary and reads accordingly, then returns the packet.

        :param validate_checksum: Set to True to validate the checksum. Set to False to skip validation. Defaults to True.

        :return: POD packet beginning with STX and ending with ETX. This may be a \
        control packet, data packet, or an unformatted packet (STX+something+ETX). 
        """
        # start packet with STX
        packet: bytes = PodPacket.STX
        # read next 4 bytes of the command number 
        cmd: bytes = self._read_get_command(validate_checksum=validate_checksum)
        packet += cmd 
        # return packet if cmd ends in ETX
        if(cmd[len(cmd)-1].to_bytes(1,'big') == PodPacket.ETX) : 
            return(PodPacket(packet))
        # determine the command number
        cmd_num: int = conv.ascii_bytes_to_int(cmd)
        # check if command number is valid
        if( not self._commands.does_command_exist(cmd_num) ) :
            raise Exception('Cannot read an invalid command: ', cmd_num)
        # then check if it is standard or binary
        if( self._commands.is_command_binary(cmd_num) ) : # binary read
            packet: DataPacket = self._read_binary(pre_packet=packet, validate_checksum=validate_checksum)
        else : # standard read
            packet: ControlPacket = self._read_standard(pre_packet=packet, validate_checksum=validate_checksum)
        # return packet
        return(packet)


    def _read_get_command(self, validate_checksum:bool=True) -> bytes : 
        """Reads one byte at a time up to 4 bytes to get the ASCII-encoded bytes command number. For each \
        byte read, it can (1) start the recursion over if an STX is found, (2) returns if ETX is found, or \
        (3) continue building the command number. 

        :param validate_checksum: Set to True to validate the checksum. Set to False to skip validation. Defaults to True.

        :return: 4 byte long string containing the ASCII-encoded command number.
        """
        # initialize 
        cmd = None
        cmd_counter = 0
        # read next 4 bytes to get command number
        while(cmd_counter < 4) : 
            # read next byte 
            b = self._port.read(1)
            cmd_counter += 1
            # build command packet 
            if(cmd == None) : 
                cmd = b
            else : 
                cmd += b
            # start over if STX is found 
            if(b == PodPacket.STX ) : 
                self._read_pod_packet_recursive(validate_checksum=validate_checksum)
            # return if ETX is found
            if(b == PodPacket.ETX ) : 
                return(cmd)
        # return complete 4 byte long command packet
        return(cmd)


    def _read_to_etx(self, validate_checksum:bool=True) -> bytes : 
        """Reads one byte at a time until an ETX is found. It will restart the recursive read if an STX \
        is found anywhere. 

        :param validate_checksum: Set to True to validate the checksum. Set to False to skip validation. Defaults to True.

        :returns: Bytes string ending with ETX.
        """
        # initialize 
        packet = None
        b = None
        # stop reading after finding ETX
        while(b != PodPacket.ETX) : 
            # read next byte
            b = self._port.read(1)
            # build packet 
            if(packet == None) : 
                packet = b
            else : 
                packet += b
            # start over if STX
            if(b == PodPacket.STX) : 
                self._read_pod_packet_recursive(validate_checksum=validate_checksum)
        # return packet
        return(packet)


    def _read_standard(self, pre_packet: bytes, validate_checksum:bool=True) -> ControlPacket:
        """Reads the payload, checksum, and ETX. Then it builds the complete standard (control) POD packet in bytes. 

        :param pre_packet: Bytes string containing the beginning of a POD packet: STX (1 byte) + command number (4 bytes).
        :param validate_checksum: Set to True to validate the checksum. Set to False to skip validation. Defaults to True.

        :return: Complete standard POD packet.
        """
        # read until ETX 
        packet = pre_packet + self._read_to_etx(validate_checksum=validate_checksum)
        # check for valid  
        if(validate_checksum) :
            if( not self._validate_checksum(packet) ) :
                raise Exception('Bad checksum for standard POD packet read.')
        # return packet
        return self._control_packet_factory(packet)


    def _read_binary(self, pre_packet: bytes, validate_checksum:bool=True) -> DataPacket :
        """Reads the remaining part of the variable-length binary packet. It first reads the standard \
        packet (pre_packet+payload+checksum+ETX). Then it determines how long the binary packet is from the \
        payload of the standard POD packet and reads that many bytes. It then reads to ETX to get the \
        checksum+ETX. 

        :param pre_packet: Bytes string containing the beginning of a POD packet: STX (1 byte) + command number (4 bytes)
        :param validate_checksum:  Set to True to validate the checksum. Set to False to skip validation. Defaults to True.

        :return: Variable-length data POD packet.
        """
        # Variable binary packet: contain a normal POD packet with the binary command, 
        #   and the payload is the length of the binary portion. The binary portion also 
        #   includes an ASCII checksum and ETX.        
        # read standard POD packet 
        start_packet: ControlPacket = self._read_standard(pre_packet, validate_checksum=validate_checksum)
        # get length of binary packet 
        num_of_binary_bytes: int = start_packet.payload[0]
        # read binary packet
        binary_msg = self._port.read(num_of_binary_bytes)
        # read csm and etx
        binary_end = self._read_to_etx(validate_checksum=validate_checksum)
        # build complete message
        packet = start_packet.raw_packet + binary_msg + binary_end
        # check if checksum is correct 
        if(validate_checksum):
            csm_calc = Pod.checksum(binary_msg)
            csm = binary_end[0:2]
            if(csm != csm_calc) : 
                raise Exception('Bad checksum for binary POD packet read.')
        # return complete variable length binary packet
        return DataPacket(packet)
