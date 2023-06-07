"""
POD_Basics handles basic communication with a POD device, including reading and writing packets and packet interpretation.
"""

# local imports
from SerialCommunication    import COM_io
from PodPacketHandling      import POD_Packets
from PodCommands            import POD_Commands

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class POD_Basics : 

    # ============ GLOBAL CONSTANTS ============    ========================================================================================================================


    # number of active POD devices, maintained by __init__ and __del__ 
    __numPod : int = 0

    # minimum packet lengths 
    __MINSTANDARDLENGTH : int = 8       # STX (1 byte) + command number (4 bytes) + optional packet  (? bytes) + checksum (2 bytes) + ETX (1 bytes)
    __MINBINARYLENGTH   : int = 15      # STX (1 byte) + command number (4 bytes) + length of binary (4 bytes) + checksum (2 bytes) + ETX (1 bytes)    <-- STANDARD POD COMMAND
                                        #   + binary (LENGTH bytes) + checksum (2 bytes) + ETX (1 bytes)                                               <-- BINARY DATA

    # ============ DUNDER METHODS ============      ========================================================================================================================


    def __init__(self, port: str|int, baudrate:int=9600) -> None : 
        # initialize serial port 
        print("com_io testing")
        self._port : COM_io = COM_io(port, baudrate)
        # create object to handle commands 
        #print(port)
        self._commands : POD_Commands = POD_Commands()
        # increment number of POD device counter
        POD_Basics.__numPod += 1


    def __del__(self) -> None :
        # decrement number of POD device counter
        POD_Basics.__numPod -= 1
        # close port
        self._port.CloseSerialPort()


    # ============ STATIC METHODS ============      ========================================================================================================================
    

    # ------------ CLASS GETTERS ------------   ------------------------------------------------------------------------------------------------------------------------


    @staticmethod
    def GetNumberOfPODDevices() -> int :
        # returns the counter tracking the number of active pod devices
        return(POD_Basics.__numPod)


    # ------------ POD PACKET COMPREHENSION ------------             ------------------------------------------------------------------------------------------------------------------------


    @staticmethod
    def UnpackPODpacket_Standard(msg: bytes) -> dict[str,bytes] : 
        # standard POD packet with optional payload = 
        #   STX (1 byte) + command number (4 bytes) + optional packet (? bytes) + checksum (2 bytes) + ETX (1 bytes)
        MINBYTES = POD_Basics.__MINSTANDARDLENGTH

        # get number of bytes in message
        packetBytes = len(msg)

        # message must have enough bytes, start with STX, or end with ETX
        if(    (packetBytes < MINBYTES)
            or (msg[0].to_bytes(1,'big') != POD_Packets.STX()) 
            or (msg[packetBytes-1].to_bytes(1,'big') != POD_Packets.ETX())
        ) : 
            raise Exception('Cannot unpack an invalid POD packet.')

        # create dict and add command number, payload, and checksum
        msg_unpacked = {}
        msg_unpacked['Command Number']  = msg[1:5]                                  # 4 bytes after STX
        if( (packetBytes - MINBYTES) > 0) : # add packet to dict, if available 
            msg_unpacked['Payload']     = msg[5:(packetBytes-3)]                    # remaining bytes between command number and checksum 

        # return unpacked POD command
        return(msg_unpacked)


    @staticmethod
    def UnpackPODpacket_Binary(msg: bytes) -> dict[str,bytes]: 
        # variable binary POD packet = 
        #   STX (1 byte) + command number (4 bytes) + length of binary (4 bytes) + checksum (2 bytes) + ETX (1 bytes)    <-- STANDARD POD COMMAND
        #   + binary (LENGTH bytes) + checksum (2 bytes) + ETX (1 bytes)                                                 <-- BINARY DATA
        MINBYTES = POD_Basics.__MINBINARYLENGTH

        # get number of bytes in message
        packetBytes = len(msg)

        # message must have enough bytes, start with STX, have ETX after POD command, or end with ETX
        if(    (packetBytes < MINBYTES)                        
            or (msg[0].to_bytes(1,'big') != POD_Packets.STX()) 
            or (msg[11].to_bytes(1,'big') != POD_Packets.ETX())
            or (msg[packetBytes-1].to_bytes(1,'big') != POD_Packets.ETX())
        ) : 
            raise Exception('Cannot unpack an invalid POD packet.')

        # create dict and add command number and checksum
        msg_unpacked = {
            'Command Number'        : msg[1:5],                                 # 4 bytes after STX
            'Binary Packet Length'  : msg[5:9],                                 # 4 bytes after command number 
            'Binary Data'           : msg[12:(packetBytes-3)],                  # ? bytes after ETX
        }

        # return unpacked POD command with variable length binary packet 
        return(msg_unpacked)
        
    
    def TranslatePODpacket_Standard(self, msg: bytes) -> dict[str,int] : 
        # unpack parts of POD packet into dict
        msgDict = POD_Basics.UnpackPODpacket_Standard(msg)
        # initialize dictionary for translated values 
        msgDictTrans = {}
        # translate the binary ascii encoding into a readable integer
        msgDictTrans['Command Number']  = POD_Packets.AsciiBytesToInt(msgDict['Command Number'])
        if( 'Payload' in msgDict) :
            # get payload bytes
            pldBytes = msgDict['Payload']
            # get sizes 
            pldSizes = (len(pldBytes),)
            argSizes = self._commands.ArgumentHexChar(msgDictTrans['Command Number'])
            retSizes = self._commands.ReturnHexChar(msgDictTrans['Command Number'])
            # determine which size tuple to use
            if( sum(pldSizes) == sum(argSizes)):
                useSizes = argSizes
            elif( sum(pldSizes) == sum(retSizes)):
                useSizes = retSizes
            else:
                useSizes = pldSizes
            # split up payload using tuple of sizes 
            pldSplit = [None]*len(useSizes)
            startByte = 0
            for i in range(len(useSizes)) : 
                # count to stop byte
                endByte = startByte + useSizes[i]
                # get bytes 
                pldSplit[i] = POD_Packets.AsciiBytesToInt(pldBytes[startByte:endByte])
                # get new start byte
                startByte = endByte
            # save translated payload
            msgDictTrans['Payload'] = tuple(pldSplit)
        # return translated unpacked POD packet 
        return(msgDictTrans)

   
    @staticmethod
    def TranslatePODpacket_Binary(msg: bytes) -> dict[str,int|bytes] : 
        # unpack parts of POD packet into dict
        msgDict = POD_Basics.UnpackPODpacket_Standard(msg)
        # initialize dictionary for translated values 
        msgDictTrans = {}
        # translate the binary ascii encoding into a readable integer
        msgDictTrans['Command Number']          = POD_Packets.AsciiBytesToInt(msgDict['Command Number'])
        msgDictTrans['Binary Packet Length']    = POD_Packets.AsciiBytesToInt(msgDict['Binary Packet Length'])
        msgDictTrans['Binary Data']             = msgDict['Binary Data'] # leave this as bytes, change type if needed 
        # return translated unpacked POD packet 
        return(msgDictTrans)


    # ------------ CHECKSUM HANDLING ------------             ------------------------------------------------------------------------------------------------------------------------


    @staticmethod
    def _ValidateChecksum(msg: bytes) -> bool :
        # ... assume that msg contains STX + packet + csm + ETX. This assumption is good for more all pod packets except variable length binary packet
        # get length of POD packet 
        packetBytes = len(msg)
        # check that packet begins with STX and ends with ETX
        if(    (msg[0].to_bytes(1,'big') != POD_Packets.STX()) 
            or (msg[packetBytes-1].to_bytes(1,'big') != POD_Packets.ETX())
        ) : 
            raise Exception('Cannot calculate the checksum of an invalid POD packet. The packet must begin with STX and end with ETX.')
        # get message contents excluding STX/ETX
        msgPacket = msg[1:packetBytes-3]
        msgCsm = msg[packetBytes-3:packetBytes-1]
        # calculate checksum from content packet  
        csmValid = POD_Packets.Checksum(msgPacket)
        # return True if checksums match 
        if(msgCsm == csmValid) :
            return(True)
        else:
            return(False)

        
    # ============ PUBLIC METHODS ============      ========================================================================================================================


    # ------------ COMMAND DICT ACCESS ------------ ------------------------------------------------------------------------------------------------------------------------
        

    def GetDeviceCommands(self) -> dict[int, list[str|tuple[int]|bool]]:
        # Get commands from this instance's command dict object 
        return(self._commands.GetCommands())


    def SetBaudrateOfDevice(self, baudrate: int) -> bool : 
        # set baudrate of the open COM port. Returns true if successful.
        return(self._port.SetBaudrate(baudrate))


    # ------------ SIMPLE POD PACKET COMPREHENSION ------------             ------------------------------------------------------------------------------------------------------------------------
    

    def UnpackPODpacket(self, msg: bytes) -> dict[str,bytes] : 
        # get command number 
        cmd = POD_Packets.AsciiBytesToInt(msg[1:5]) # same for standard and binary packets 
        if(self._commands.IsCommandBinary(cmd)):
            # message is binary 
            return(self.UnpackPODpacket_Binary(msg))
        else:
            return(self.UnpackPODpacket_Standard(msg))


    def TranslatePODpacket(self, msg: bytes) -> dict[str,int|bytes] : 
        # get command number 
        cmd = POD_Packets.AsciiBytesToInt(msg[1:5]) # same for standard and binary packets 
        if(self._commands.IsCommandBinary(cmd)):
            # message is binary 
            return(self.TranslatePODpacket_Binary(msg))
        else:
            return(self.TranslatePODpacket_Standard(msg))
    

    # ------------ POD COMMUNICATION ------------   ------------------------------------------------------------------------------------------------------------------------


    def WriteRead(self, cmd: str|int, payload:int|bytes|tuple[int|bytes]=None, validateChecksum:bool=True) -> bytes :
        self.WritePacket(cmd, payload)
        r = self.ReadPODpacket(validateChecksum)
        return(r)


    def GetPODpacket(self, cmd: str|int, payload:int|bytes|tuple[int|bytes]=None) -> bytes :
        # return False if command is not valid
        print(cmd)
        print(payload)
        if(not self._commands.DoesCommandExist(cmd)) : 
            raise Exception('POD command does not Exist.')
        # get command number 
        if(isinstance(cmd,str)):
            cmdNum = self._commands.CommandNumberFromName(cmd)
        else: 
            cmdNum = cmd
        # get length of expected paylaod 
        argSizes = self._commands.ArgumentHexChar(cmdNum)
        # check if command requires a payload.
        #   

        if( sum(argSizes) > 0 ): 
            # check to see if a payload was given 
            if(payload == None):
                raise Exception('POD command requires a payload.')
            # get payload in bytes
            pld = POD_Packets.PayloadToBytes(payload, argSizes)
            #pld = '11'
            print(pld)
            print(type(pld))
            print(argSizes)
            print(type(argSizes))
        else :
            pld = None
        # build POD packet 
        
        packet = POD_Packets.BuildPODpacket_Standard(cmdNum, payload=pld)
        print(packet)
        # return complete packet 
        return(packet)
    

    def WritePacket(self, cmd: str|int, payload:int|bytes|tuple[int|bytes]=None) -> bytes :                     
        # POD packet 
        # print("enter write")
        packet = self.GetPODpacket(cmd, payload)
        #print("write packet testing")
        # print("packet")
        # write packet to serial port 
        self._port.Write(packet)
        # returns packet that was written
        return(packet)


    def ReadPODpacket(self, validateChecksum:bool=True) -> bytes :
        # read until STX is found
        # print("readpod")
        b = None
        while(b != POD_Packets.STX()) :
            b = self._port.Read(1)     # read next byte  
        # continue reading packet  
        packet = self._ReadPODpacket_Recursive(validateChecksum=validateChecksum)
        # return final packet
        return(packet)


    # ============ PROTECTED METHODS ============      ========================================================================================================================


    # ------------ POD COMMUNICATION ------------   ------------------------------------------------------------------------------------------------------------------------

    def _ReadPODpacket_Recursive(self, validateChecksum:bool=True) -> bytes : 
        # start packet with STX
        packet = POD_Packets.STX()

        # read next 4 bytes of the command number 
        cmd = self._Read_GetCommand(validateChecksum=validateChecksum)
        packet += cmd 

        # return packet if cmd ends in ETX
        if(cmd[len(cmd)-1].to_bytes(1,'big') == POD_Packets.ETX()) : 
            return(packet)

        # determine the command number
        cmdNum = POD_Packets.AsciiBytesToInt(cmd)

        # check if command number is valid
        if( not self._commands.DoesCommandExist(cmdNum) ) :
            raise Exception('Cannot read an invalid command: ', cmdNum)
        

        # then check if it is standard or binary
        if( self._commands.IsCommandBinary(cmdNum) ) : 
            # binary read
            packet = self._Read_Binary(prePacket=packet, validateChecksum=validateChecksum)
        else : 
            # standard read 
            packet = self._Read_Standard(prePacket=packet, validateChecksum=validateChecksum)

        # return packet
        return(packet)


    def _Read_GetCommand(self, validateChecksum:bool=True) -> bytes : 
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
            if(b == POD_Packets.STX() ) : 
                self._ReadPODpacket_Recursive(validateChecksu=validateChecksum)
            # return if ETX is found
            if(b == POD_Packets.ETX() ) : 
                return(cmd)

        # return complete 4 byte long command packet
        return(cmd)

    def _Read_ToETX(self, validateChecksum:bool=True) -> bytes : 
        # initialize 
        packet = None
        b = None
        # stop reading after finding ETX
        while(b != POD_Packets.ETX()) : 
            # read next byte
            b = self._port.Read(1)
            # build packet 
            if(packet == None) : 
                packet = b
            else : 
                packet += b
            # start over if STX
            if(b == POD_Packets.STX()) : 
                self._ReadPODpacket_Recursive(validateChecksum=validateChecksum)
        # return packet
        return(packet)


    def _Read_Standard(self, prePacket: bytes, validateChecksum:bool=True) -> bytes:
        # read until ETX 
        packet = prePacket + self._Read_ToETX(validateChecksum=validateChecksum)
        # check for valid  
        if(validateChecksum) :
            if( not self._ValidateChecksum(packet) ) :
                raise Exception('Bad checksum for standard POD packet read.')
        # return packet
        return(packet)


    def _Read_Binary(self, prePacket: bytes, validateChecksum:bool=True) -> bytes :
        # Variable binary packet: contain a normal POD packet with the binary command, 
        #   and the payload is the length of the binary portion. The binary portion also 
        #   includes an ASCII checksum and ETX.        
         
        # read standard POD packet 
        startPacket = self._Read_Standard(prePacket, validateChecksum=validateChecksum)
        startDict   = self.UnpackPODpacket_Standard(startPacket)

        # get length of binary packet 
        numOfbinaryBytes = POD_Packets.AsciiBytesToInt(startDict['Payload'])

        # read binary packet
        binaryMsg = self._port.Read(numOfbinaryBytes) # read binary packet

        # read csm and etx
        binaryEnd = self._Read_ToETX(validateChecksum=validateChecksum)

        # build complete message
        packet = startPacket + binaryMsg + binaryEnd

        # check if checksum is correct 
        if(validateChecksum):
            csmCalc = POD_Packets.Checksum(binaryMsg)
            csm = binaryEnd[0:2]
            if(csm != csmCalc) : 
                raise Exception('Bad checksum for binary POD packet read.')

        # return complete variable length binary packet
        return(packet)

