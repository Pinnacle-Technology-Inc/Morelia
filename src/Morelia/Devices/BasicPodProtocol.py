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
    def GetU(u: int) -> int : 
        """Number of hexadecimal characters for an unsigned u-bit value.

        :param u: 8, 16, or 32 bits. Enter any other number for NOVALUE.

        :return: number of hexadecimal characters for an unsigned u-bit value.
        """
        match u : 
            case  8: return(CommandSet.U8())
            case 16: return(CommandSet.U16())
            case 32: return(CommandSet.U32())
            case  _: return(CommandSet.NoValue())

    @property
    def device_name(self) -> str:
        """The virtual device name."""
        return self._device_name

    @staticmethod
    def ChoosePort(forbidden:list[str]=[]) -> str : 
        """Checks user's Operating System, and chooses ports accordingly.

        :param forbidden: List of port names that are already used. Defaults to an empty list.

        :return: Name of the port.
        """
        return FindPorts.ChoosePort(forbidden)

    # ------------ CHECKSUM HANDLING ------------   ------------------------------------------------------------------------------------------------------------------------


    @staticmethod
    def _ValidateChecksum(msg: bytes) -> bool :
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
        packetBytes = len(msg)
        # check that packet begins with STX and ends with ETX
        if(    (msg[0].to_bytes(1,'big') != PodPacket.STX) 
            or (msg[packetBytes-1].to_bytes(1,'big') != PodPacket.ETX)
        ) : 
            raise InvalidChecksumError('Cannot calculate the checksum of an invalid POD packet. The packet must begin with STX and end with ETX.')
        # get message contents excluding STX/ETX
        msgPacket = msg[1:packetBytes-3]
        msgCsm = msg[packetBytes-3:packetBytes-1]
        # calculate checksum from content packet  
        csmValid = Pod.Checksum(msgPacket)
        # return True if checksums match 
        if(msgCsm == csmValid) :
            return(True)
        else:
            return(False)



    @staticmethod
    def Checksum(bytesIn: bytes) -> bytes:
        """Calculates the checksum of a given bytes message. This is achieved by summing each byte in the 
        message, inverting, and taking the last byte.

        :param bytesIn: Bytes message containing POD packet data.

        :return: Two ASCII-encoded bytes containing the checksum for ``bytesIn``.
        """
        # sum together all bytes in byteArr
        sum = 0
        for b in bytesIn : 
            sum = sum + b
        # invert and get last byte 
        cs  = ~sum & 0xFF
        # convert int into bytes 
        cs_bytes = conv.int_to_ascii_bytes(cs, 2)
        # return checksum bytes
        return(cs_bytes)


    @staticmethod
    def BuildPODpacket_Standard(commandNumber: int, payload:bytes|None=None) -> bytes : 
        """Builds a standard POD packet (control packet) as bytes: STX (1 byte) + command number (4 bytes) \
        + optional packet (? bytes) + checksum (2 bytes)+ ETX (1 bytes).

        :param commandNumber: Integer representing the command number. This will be converted into a \
        4 byte long ASCII-encoded bytes string.
        :param payload: bytes string containing the payload. Defaults to None.

        :return: Bytes string of a complete standard POD packet.
        """
        # prepare components of packet
        stx = PodPacket.STX                              # STX indicating start of packet (1 byte)
        cmd = conv.int_to_ascii_bytes(commandNumber, 4)  # command number (4 bytes)
        etx = PodPacket.ETX                              # ETX indicating end of packet (1 byte)
        # build packet with payload 
        if(payload) :
            csm = Pod.Checksum(cmd+payload)         # checksum (2 bytes)
            packet = stx + cmd + payload + csm + etx        # pod packet with payload (8 + payload bytes)
        # build packet with NO payload 
        else :
            csm = Pod.Checksum(cmd)                 # checksum (2 bytes)
            packet = stx + cmd + csm + etx                  # pod packet (8 bytes)
        # return complete bytes packet
        return(packet)

    
    @staticmethod
    def PayloadToBytes(payload: int|bytes|tuple[int|bytes], argSizes: tuple[int]) -> bytes :
        """Converts a payload into a bytes string (assuming that the payload is for a valid command).

            :param payload: Integer, bytes, or tuple containing the payload.
            :param argSizes: Tuple of the argument sizes.

            :return: Bytes string of the payload.
        """
        # if integer payload is given ... 
        if(isinstance(payload,int)):
            # convert to bytes of the expected length 
            pld = conv.int_to_ascii_bytes(payload,sum(argSizes))
        # if bytes payload is given...
        elif(isinstance(payload, bytes)):
            pld = payload
        # if tuple payload is given...
        else: 
            # build list of bytes payload parts 
            tempPld = [None]*len(payload)
            for i in range(len(payload)) : 
                if(isinstance(payload[i], int)) :
                    # convert to bytes of the expected length 
                    tempPld[i] = conv.int_to_ascii_bytes(payload[i],argSizes[i])
                else : 
                    # accept bytes payload as given
                    tempPld[i] = payload[i]
            # concatenate list items
            pld = tempPld[0]
            for i in range(len(tempPld)-1):
                pld += tempPld[i+1]
        # return payload as bytes
        return(pld)
            
    

    def FlushPort(self) -> bool : 
        """Reset the input and output serial port buffer.

        :return: True of the buffers are flushed, False otherwise.
        """
        return(self._port.Flush())
    
    
    def SetBaudrateOfDevice(self, baudrate: int) -> bool : 
        """If the port is open, it will change the baud rate to the parameter's value.

        :param baudrate: Baud rate to set for the open serial port. 

        :return: True if successful at setting the baud rate, false otherwise.
        """
        # set baudrate of the open COM port. Returns true if successful.
        return(self._port.SetBaudrate(baudrate))


    def GetDeviceCommands(self) -> dict[int, list[str|tuple[int]|bool]]:
        """Gets the dictionary containing the class instance's available POD commands.

        :return: Dictionary containing the available commands and their \
                information.Formatted as key(command number) : value([command name, number of argument \
                ASCII bytes, number of return bytes, binary flag ])
        """
        # Get commands from this instance's command dict object 
        return(self._commands.GetCommands())
    
    def TestConnection(self, pingCmd:str|int='PING') -> bool :
        """Tests if a POD device can be read from or written. Sends a PING command. 

        :param pingCmd: Command name or number to ping. Defaults to 'PING'.

        :return: True for successful connection, false otherwise.
            
        """
        if(not self._commands.DoesCommandExist(pingCmd)) : 
            raise Exception('[!] Ping command \''+str(pingCmd)+'\' does not exist for this POD device.')
        # returns True when connection is successful, false otherwise
        try:
            self.FlushPort() # clear out any unread packets 
            w: ControlPacket = self.WritePacket(cmd=pingCmd)
            r: PodPacket = self.ReadPODpacket()
        except:   return(False)
        # check that read matches ping write
        if(w ==r ): return(True)
        return(False)
    

    def GetPODpacket(self, cmd: str|int, payload:int|bytes|tuple[int|bytes]=None) -> bytes :
        """Builds a POD packet and writes it to a POD device via COM port. If an integer payload is give, \
        the method will convert it into a bytes string of the length expected by the command. If a bytes \
        payload is given, it must be the correct length. 

        :param cmd: Command number. 
        :param payload: None when there is no payload. If there is a payload, set to an integer value, bytes string, or tuple. Defaults to None.

        :return: Bytes string of the POD packet. 
        """
        # return False if command is not valid
        if(not self._commands.DoesCommandExist(cmd)) : 
            raise Exception('POD command does not exist.')
        # get command number 
        if(isinstance(cmd,str)):
            cmdNum : int = self._commands.CommandNumberFromName(cmd)
        else: 
            cmdNum : int = cmd
        # get length of expected paylaod 
        argSizes = self._commands.ArgumentHexChar(cmdNum)
        # check if command requires a payload
        if( sum(argSizes) > 0 ): 
            # raise exception if command is invalid
            self._commands.ValidateCommand(cmdNum, payload)
            # get payload in bytes
            pld = Pod.PayloadToBytes(payload, argSizes)
        else :
            pld = None
        # build POD packet 
        packet = Pod.BuildPODpacket_Standard(cmdNum, payload=pld)
        # return complete packet 
        return(packet)
    
    def WriteRead(self, cmd: str|int, payload:int|bytes|tuple[int|bytes]=None, validateChecksum:bool=True, timeout_sec: int|float = 5) -> PodPacket :
        """Writes a command with optional payload to POD device, then reads (once) the device response.

        :param cmd: Command number. 
        :param payload: None when there is no payload. If there is a payload, set to an integer value or a bytes string. Defaults to None.
        :param validateChecksum: Set to True to validate the checksum. Set to False to skip validation. Defaults to True.

        :return: POD packet beginning with STX and ending with ETX. This may \
                be a control packet, data packet, or an unformatted packet (STX+something+ETX). 
        """
        self.WritePacket(cmd, payload)
        r = self.ReadPODpacket(validateChecksum, timeout_sec)
        return(r)


    def WritePacket(self, cmd: str|int, payload:int|bytes|tuple[int|bytes]=None) -> ControlPacket:
        """Builds a POD packet and writes it to the POD device. 

        :param cmd: Command number.
        :param payload: None when there is no payload. If there is a payload, set to an integer value, bytes string, or tuple. Defaults to None.

        :return: Packet that was written to the POD device.
        """
        # POD packet 
        packet = self.GetPODpacket(cmd, payload)
        # write packet to serial port 
        self._port.Write(packet)
        # returns packet that was written
        return ControlPacket(self._commands, packet)


    def ReadPODpacket(self, validateChecksum:bool=True, timeout_sec: int|float = 5) -> PodPacket :
        """Reads a complete POD packet, either in standard or binary format, beginning with STX and \
        ending with ETX. Reads first STX and then starts recursion. 

        :param validateChecksum: Set to True to validate the checksum. Set to False to skip validation. Defaults to True.
        :param timeout_sec: Time in seconds to wait for serial data. Defaults to 5. 

        :return: POD packet beginning with STX and ending with ETX. This may be a \
        control packet, data packet, or an unformatted packet (STX+something+ETX). 
        """
        # read until STX is found
        b = None
        while(b != PodPacket.STX) :
            b = self._port.Read(1,timeout_sec)     # read next byte  
        # continue reading packet  
        packet = self._ReadPODpacket_Recursive(validateChecksum=validateChecksum)
        # return final packet
        return(packet)




    def _ReadPODpacket_Recursive(self, validateChecksum:bool=True) -> PodPacket : 
        """Reads the command number. If the command number ends in ETX, the packet is returned. \
        Next, it checks if the command is allowed. Then, it checks if the command is standard or \
        binary and reads accordingly, then returns the packet.

        :param validateChecksum: Set to True to validate the checksum. Set to False to skip validation. Defaults to True.

        :return: POD packet beginning with STX and ending with ETX. This may be a \
        control packet, data packet, or an unformatted packet (STX+something+ETX). 
        """
        # start packet with STX
        packet: bytes = PodPacket.STX
        # read next 4 bytes of the command number 
        cmd: bytes = self._Read_GetCommand(validateChecksum=validateChecksum)
        packet += cmd 
        # return packet if cmd ends in ETX
        if(cmd[len(cmd)-1].to_bytes(1,'big') == PodPacket.ETX) : 
            return(PodPacket(packet))
        # determine the command number
        cmdNum: int = conv.ascii_bytes_to_int(cmd)
        # check if command number is valid
        if( not self._commands.DoesCommandExist(cmdNum) ) :
            raise Exception('Cannot read an invalid command: ', cmdNum)
        # then check if it is standard or binary
        if( self._commands.IsCommandBinary(cmdNum) ) : # binary read
            packet: DataPacket = self._Read_Binary(prePacket=packet, validateChecksum=validateChecksum)
        else : # standard read
            packet: ControlPacket = self._Read_Standard(prePacket=packet, validateChecksum=validateChecksum)
        # return packet
        return(packet)


    def _Read_GetCommand(self, validateChecksum:bool=True) -> bytes : 
        """Reads one byte at a time up to 4 bytes to get the ASCII-encoded bytes command number. For each \
        byte read, it can (1) start the recursion over if an STX is found, (2) returns if ETX is found, or \
        (3) continue building the command number. 

        :param validateChecksum: Set to True to validate the checksum. Set to False to skip validation. Defaults to True.

        :return: 4 byte long string containing the ASCII-encoded command number.
        """
        # initialize 
        cmd = None
        cmdCounter = 0
        # read next 4 bytes to get command number
        while(cmdCounter < 4) : 
            # read next byte 
            b = self._port.Read(1)
            cmdCounter += 1
            # build command packet 
            if(cmd == None) : 
                cmd = b
            else : 
                cmd += b
            # start over if STX is found 
            if(b == PodPacket.STX ) : 
                self._ReadPODpacket_Recursive(validateChecksum=validateChecksum)
            # return if ETX is found
            if(b == PodPacket.ETX ) : 
                return(cmd)
        # return complete 4 byte long command packet
        return(cmd)


    def _Read_ToETX(self, validateChecksum:bool=True) -> bytes : 
        """Reads one byte at a time until an ETX is found. It will restart the recursive read if an STX \
        is found anywhere. 

        :param validateChecksum: Set to True to validate the checksum. Set to False to skip validation. Defaults to True.

        :returns: Bytes string ending with ETX.
        """
        # initialize 
        packet = None
        b = None
        # stop reading after finding ETX
        while(b != PodPacket.ETX) : 
            # read next byte
            b = self._port.Read(1)
            # build packet 
            if(packet == None) : 
                packet = b
            else : 
                packet += b
            # start over if STX
            if(b == PodPacket.STX) : 
                self._ReadPODpacket_Recursive(validateChecksum=validateChecksum)
        # return packet
        return(packet)


    def _Read_Standard(self, prePacket: bytes, validateChecksum:bool=True) -> ControlPacket:
        """Reads the payload, checksum, and ETX. Then it builds the complete standard (control) POD packet in bytes. 

        :param prePacket: Bytes string containing the beginning of a POD packet: STX (1 byte) + command number (4 bytes).
        :param validateChecksum: Set to True to validate the checksum. Set to False to skip validation. Defaults to True.

        :return: Complete standard POD packet.
        """
        # read until ETX 
        packet = prePacket + self._Read_ToETX(validateChecksum=validateChecksum)
        # check for valid  
        if(validateChecksum) :
            if( not self._ValidateChecksum(packet) ) :
                raise Exception('Bad checksum for standard POD packet read.')
        # return packet
        return self._control_packet_factory(packet)


    def _Read_Binary(self, prePacket: bytes, validateChecksum:bool=True) -> DataPacket :
        """Reads the remaining part of the variable-length binary packet. It first reads the standard \
        packet (prePacket+payload+checksum+ETX). Then it determines how long the binary packet is from the \
        payload of the standard POD packet and reads that many bytes. It then reads to ETX to get the \
        checksum+ETX. 

        :param prePacket: Bytes string containing the beginning of a POD packet: STX (1 byte) + command number (4 bytes)
        :param validateChecksum:  Set to True to validate the checksum. Set to False to skip validation. Defaults to True.

        :return: Variable-length data POD packet.
        """
        # Variable binary packet: contain a normal POD packet with the binary command, 
        #   and the payload is the length of the binary portion. The binary portion also 
        #   includes an ASCII checksum and ETX.        
        # read standard POD packet 
        startPacket: ControlPacket = self._Read_Standard(prePacket, validateChecksum=validateChecksum)
        # get length of binary packet 
        numOfbinaryBytes: int = startPacket.payload[0]
        # read binary packet
        binaryMsg = self._port.Read(numOfbinaryBytes)
        # read csm and etx
        binaryEnd = self._Read_ToETX(validateChecksum=validateChecksum)
        # build complete message
        packet = startPacket.raw_packet + binaryMsg + binaryEnd
        # check if checksum is correct 
        if(validateChecksum):
            csmCalc = Pod.Checksum(binaryMsg)
            csm = binaryEnd[0:2]
            if(csm != csmCalc) : 
                raise Exception('Bad checksum for binary POD packet read.')
        # return complete variable length binary packet
        return DataPacket(packet)
