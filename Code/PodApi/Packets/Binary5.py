# enviornment imports
from typing import Any

# local imports
from PodApi.Commands import Commands
from PodApi.Packets  import Packet

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

# -----------------------------------------------------------------------------
# Binary 5 Data Format
# -----------------------------------------------------------------------------		
# Byte    Value	                        Format      Description 
# -----------------------------------------------------------------------------		
# 0	    0x02	                        Binary		STX
# 1	    0	                            ASCII		Command Number Byte 0
# 2	    0	                            ASCII		Command Number Byte 1
# 3	    B	                            ASCII		Command Number Byte 2
# 4	    5	                            ASCII		Command Number Byte 3
# 5	    Packet Number 	                Binary		A rolling value that increases with each packet, and rolls over to 0 after it hits 255
# 6	    Status	                        Binary		Status byte, currently unused
# 7	    CH3 17~10	                    Binary		Top 8 bits of CH3.  Data is 18 bits, packed over 3 bytes.  Because of this the number of bits in each byte belonging to each chanenl changes.  Values are sent MSB/MSb first
# 8	    CH3 9~2	                        Binary		Middle 8 bits of CH3
# 9	    CH3 1~0, CH2 17~12	            Binary		Bottom 2 bits of CH3 and top 6 bits of CH2
# 10	CH2 11~4	                    Binary		Middle 8 bits of Ch2
# 11	CH2 3~0, CH1 17~14	            Binary		Bottom 4 bits of CH2 and top 4 bits of CH1
# 12	CH1 13~6	                    Binary		Middle 8 bits of CH1
# 13	CH1 5~0, CH0 17~16	            Binary		Bottom 6 bits of CH1 and top 2 bits of CH0
# 14	CH0 15~8	                    Binary		Middle 8 bits of Ch0
# 15	CH0 7~0	                        Binary		Bottom 8 bits of CH0
# 16	EXT0 Analog Value High Byte	    Binary		Top nibble of the 12-bit EXT0 analog value.  Sent MSB/MSb first
# 17	EXT0 Analog Value Low Byte	    Binary		Bottom nibble of the EXT0 value
# 18	EXT1 Analog Value High Byte	    Binary		Top nibble of the 12-bit EXT1 analog value.  Sent MSB/MSb first
# 19	EXT1 Analog Value Low Byte	    Binary		Bottom nibble of the EXT1 value
# 20	TTL1 Analog Value High Byte	    Binary		Top nibble of the TTL1 pin read as a 12-bit analog value
# 21	TTL1 Analog Value Low Byte	    Binary		Bottom nibble of the TTL2 pin analog value
# 22	TTL2 Analog Value High Byte	    Binary		Top nibble of the TTL1 pin read as a 12-bit analog value
# 23	TTL2 Analog Value Low Byte	    Binary		Bottom nibble of the TTL2 pin analog value
# 24	TTL3 Analog Value High Byte	    Binary		Top nibble of the TTL3 pin read as a 12-bit analog value
# 25	TTL3 Analog Value Low Byte	    Binary		Bottom nibble of the TTL3 pin analog value
# 26	TTL4 Analog Value High Byte	    Binary		Top nibble of the TTL4 pin read as a 12-bit analog value
# 27	TTL4 Analog Value Low Byte	    Binary		Bottom nibble of the TTL4 pin analog value
# 28	Checksum MSB	                ASCII		Checksum
# 29	Checksum LSB	                ASCII		Checksum 
# 30	0x03	                        Binary		ETX
# -----------------------------------------------------------------------------

class PacketBinary5(Packet) : 
    """Container class that stores a binary5 command packet for a POD device. The format is \
    STX (1 byte) + command (4 bytes) + packet number (1 byte) + status (1 byte) \
    + channels (9 bytes) + AEXT0 (2 bytes) + AEXT1 (2 bytes) + ATTL1 (2 bytes) \
    + ATTL2 (2 bytes) + ATTL3 (2 bytes) + ATTL4 (2 bytes) + checksum (2 bytes) \
    + EXT (1 byte)
    
    Attributes:
        _ssGain (dict[str,int|None]): Dictionary with A, B, C, D keys and \
            second stage gain values (1, 5, or None).
        _preampGain (dict[str,int|None]): Dictionary with A, B, C, D keys and \
            preamplifier gain values (10, 100, or None).
        packetNumber (bytes): Packet number for this POD packet.
        status (bytes): Status for this POD packet.
        channels (bytes): channel A, B, C, and D data for this POD packet.
        aEXT0 (bytes): Analog EXT0 data for this POD packet.
        aEXT1 (bytes): Analog EXT1 data for this POD packet.
        aTTL1 (bytes): Analog TTL1 data for this POD packet.
        aTTL2 (bytes): Analog TTL2 data for this POD packet.
        aTTL3 (bytes): Analog TTL3 data for this POD packet.
        aTTL4 (bytes): Analog TTL4 data for this POD packet.
    """
    
    def __init__(self, pkt: bytes,                  
                 ssGain: dict[str,int|None] = {'A':None,'B':None,'C':None,'D':None}, 
                 preampGain: dict[str,int|None] = {'A':None,'B':None,'C':None,'D':None}, 
                 commands: Commands | None = None
                ) -> None:
        """Sets the class instance variables. 

        Args:
            pkt (bytes): Bytes string containing a POD packet. Should begin with STX and \
                ending with ETX.
            ssGain (dict[str,int|None], optional): Second stage gain for four channels. Defaults to {'A':None,'B':None,'C':None,'D':None}.
            preampGain (dict[str,int|None], optional): Preamplifier gain for four channels. Defaults to {'A':None,'B':None,'C':None,'D':None}.
            commands (POD_Commands | None, optional): Available commands for a POD device. \
                Defaults to None.
        """
        super().__init__(pkt, commands)
        # packet parts
        self.packetNumber   : bytes = self.GetPacketNumber(pkt)
        self.status         : bytes = self.GetStatus(pkt)
        self.channels       : bytes = self.GetChannels(pkt)
        self.aEXT0          : bytes = self.GetAnalogEXT(0, pkt)
        self.aEXT1          : bytes = self.GetAnalogEXT(1, pkt)
        self.aTTL1          : bytes = self.GetAnalogTTL(1, pkt)
        self.aTTL2          : bytes = self.GetAnalogTTL(2, pkt)
        self.aTTL3          : bytes = self.GetAnalogTTL(3, pkt)
        self.aTTL4          : bytes = self.GetAnalogTTL(4, pkt)
        # device properties 
        self._ssGain        : dict[str,int|None] = ssGain
        self._preampGain    : dict[str,int|None] = preampGain
    
    # ----- Packet to dictionary -----
    
    def UnpackAll(self) -> dict[str, bytes]:
        """Builds a dictionary containing all parts of the POD packet in bytes. 

        Returns:
            dict[str, bytes]: Dictionary with the command number, packet number, status, \
                channels, analog EXT, and analog TTL.
        """
        data: dict = super().UnpackAll()
        data['Packet #'   ] = self.packetNumber
        data['Status'     ] = self.status 
        data['Channels'   ] = self.channels
        data['Analog EXT0'] = self.aEXT0
        data['Analog EXT1'] = self.aEXT1
        data['Analog TTL1'] = self.aTTL1
        data['Analog TTL2'] = self.aTTL2
        data['Analog TTL3'] = self.aTTL3
        data['Analog TTL4'] = self.aTTL4
        return data
    
    def TranslateAll(self) -> dict[str, Any]:
        """Builds a dictionary containing all parts of the POD packet in readable values. 

        Returns:
            dict[str, bytes]: Dictionary with the command number, packet number, status, \
                channels, analog EXT, and analog TTL.
        """
        data: dict = super().UnpackAll()
        data['Packet #'   ] = self.PacketNumber()
        data['Status'     ] = self.Status()
        for c in ['A', 'B', 'C', 'D'] :   # for each channel 
            if(self._ssGain[c] != None) : # exclude no-connects 
                data[c] = self.Channel(c) # get channel voltage 
        data['Analog EXT0'] = self.AnalogEXT(0)
        data['Analog EXT1'] = self.AnalogEXT(1)
        data['Analog TTL1'] = self.AnalogTTL(1)
        data['Analog TTL2'] = self.AnalogTTL(2)
        data['Analog TTL3'] = self.AnalogTTL(3)
        data['Analog TTL4'] = self.AnalogTTL(4)
        return data

    # ----- Translated parts -----
    
    def PacketNumber(self) -> int : 
        """Translates the binary packet number into a readable integer.

        Returns:
            int: Integer of the packet number.
        """
        return Packet.BinaryBytesToInt(self.packetNumber)
    
    def Status(self) -> int : 
        """Translates the binary status value into a readable integer

        Returns:
            int: Integer status value.
        """
        return Packet.BinaryBytesToInt(self.status)

    def Channel(self, c: str) -> float : 
        """Translates the channel data into a voltage.

        Args:
            c (str): Channel character. Should be A, B, C, or D.

        Raises:
            Exception: Channel does not exist.

        Returns:
            float: Voltage of the channel in volts (V).
        """
        match c : 
            case 'A' : chan = Packet.BinaryBytesToInt_Split(self.channels[6:9], 18, 0) #  A | 13  CH1 5~0, CH0 17~16 | 14 CH0 15~8  | 15 CH0 7~0            | --> cut top 6              bits
            case 'B' : chan = Packet.BinaryBytesToInt_Split(self.channels[4:7], 20, 2) #  B | 11  CH2 3~0, CH1 17~14 | 12 CH1 13~6  | 13 CH1 5~0, CH0 17~16 | --> cut top 4 and bottom 2 bits
            case 'C' : chan = Packet.BinaryBytesToInt_Split(self.channels[2:5], 22, 4) #  C |  9  CH3 1~0, CH2 17~12 | 10 CH2 11~4  | 11 CH2 3~0, CH1 17~14 | --> cut top 2 and bottom 4 bits
            case 'D' : chan = Packet.BinaryBytesToInt_Split(self.channels[0:3], 24, 6) #  D |  7  CH3 17~10          |  8 CH3 9~2   |  9 CH3 1~0, CH2 17~12 | --> cut           bottom 6 bits
            case  _  : raise Exception('Channel '+str(c)+' does not exist.')
        return PacketBinary5._Voltage_PrimaryChannels(chan, self._ssGain[c], self._preampGain[c])

    def AnalogEXT(self, n: int) -> float : 
        """Translates the analog EXT value into a voltage. 

        Args:
            n (int): Analog EXT number. Should be 0 or 1.

        Raises:
            Exception: AEXT does not exist.

        Returns:
            float: Analog EXT voltage in volts (V).
        """
        match n :
            case 0 : ext = self.aEXT0
            case 1 : ext = self.aEXT1
            case _ : raise Exception('AEXT'+str(n)+' does not exist.')
        return PacketBinary5._Voltage_SecondaryChannels(Packet.BinaryBytesToInt(ext))
    
    def AnalogTTL(self, n: int) -> float : 
        """Translates the analog TTL value into a voltage.

        Args:
            n (int): Analog TTL number. Should be 1, 2, 3, or 4.

        Raises:
            Exception: ATTL does not exist.

        Returns:
            float: Analog TTL voltage in volts (v).
        """
        match n:
            case 1 : ttl = self.aTTL1
            case 2 : ttl = self.aTTL2
            case 3 : ttl = self.aTTL3
            case 4 : ttl = self.aTTL4
            case _ : raise Exception('ATTL'+str(n)+' does not exist.')
        return PacketBinary5._Voltage_SecondaryChannels( Packet.BinaryBytesToInt(ttl) )
    
    # ----- Get parts from packet bytes -----
    
    @staticmethod
    def GetPacketNumber(pkt: bytes) -> bytes : 
        """Gets the packet number in bytes from a POD packet.

        Args:
            pkt (bytes): Bytes string containing a POD packet. Should begin with STX and \
                end with ETX.

        Returns:
            bytes: Bytes string of the packet number.
        """
        return pkt[5].to_bytes(1,'big')
    
    @staticmethod
    def GetStatus(pkt: bytes) -> bytes : 
        """Gets the status value in bytes from a POD packet. 

        Args:
            pkt (bytes): Bytes string containing a POD packet. Should begin with STX and \
                end with ETX.

        Returns:
            bytes: Bytes string of the status.
        """
        return pkt[6].to_bytes(1,'big')

    @staticmethod
    def GetChannels(pkt: bytes) -> bytes : 
        """Gets the channel bytes for channels A, B, C, and D together from a POD packet.

        Args:
            pkt (bytes): Bytes string containing a POD packet. Should begin with STX and \
                end with ETX.

        Returns:
            bytes: Bytes string of the channels A, B, C, and D together.
        """
        return pkt[7:16]
    
    @staticmethod
    def GetAnalogEXT(n: int, pkt: bytes) -> bytes : 
        """Gets the analog EXT from a POD packet.

        Args:
            n (int): Analog EXT number. Should be 0 or 1.
            pkt (bytes): Bytes string containing a POD packet. Should begin with STX and \
                end with ETX.

        Raises:
            Exception: AEXT does not exist.

        Returns:
            bytes: Bytes string of the AEXT.
        """
        match n :
            case 0 : return pkt[16:18]
            case 1 : return pkt[18:20]
            case _ : raise  Exception('AEXT'+str(n)+' does not exist.')
    
    @staticmethod
    def GetAnalogTTL(n: int, pkt: bytes) -> bytes : 
        """Gets the analog TTL from a POD packet.

        Args:
            n (int): Analog TTL number. Should be 1, 2, 3, or 4.
            pkt (bytes): Bytes string containing a POD packet. Should begin with STX and \
                end with ETX.

        Raises:
            Exception: ATTL does not exist.

        Returns:
            bytes: Bytes string of the ATTL.
        """
        match n:
            case 1 : return pkt[20:22]
            case 2 : return pkt[22:24]
            case 3 : return pkt[24:26]
            case 4 : return pkt[26:28]
            case _ : raise  Exception('ATTL'+str(n)+' does not exist.')
        
    # ----- Properties -----
        
    @staticmethod
    def GetMinimumLength() -> int : 
        """Gets the number of bytes in the smallest possible binary4 packet; \
        STX (1 byte) + command (4 bytes) + packet number (1 byte) + status (1 byte) \
        + channels (9 bytes) + AEXT0 (2 bytes) + AEXT1 (2 bytes) + ATTL1 (2 bytes) \
        + ATTL2 (2 bytes) + ATTL3 (2 bytes) + ATTL4 (2 bytes) + checksum (2 bytes) \
        + EXT (1 byte)

        Returns:
            int: Integer representing the minimum length of a binary5 POD packet. 
        """
        return 31
    
    @staticmethod
    def GetBinaryLength() -> int :
        """Gets the number of bytes of binary data in a binary5 packet.

        Returns:
            int: Integer representing the number of binary encoded bytes in a binary5 packet.
        """
        # length minus STX(1), command number(4), checksum(2), ETX(1) || 31 - 8 = 23
        return PacketBinary5.GetMinimumLength() - 8

    @staticmethod   
    def CheckIfPacketIsValid(msg: bytes) :
        """Raises an Exception if the packet is incorrectly formatted. 

        Args:
            msg (bytes): Bytes string containing a POD packet. Should begin with STX \
                and end with ETX.

        Raises:
            Exception: Packet the wrong size to be a binary5 packet.
        """
        Packet.CheckIfPacketIsValid(msg) 
        if(len(msg) != PacketBinary5.GetMinimumLength()) : 
            raise Exception('Packet the wrong size to be a binary5 packet.')
    
    # ----- Conversions -----

    @staticmethod
    def _Voltage_PrimaryChannels(value: int, ssGain:int|None=None, PreampGain:int|None=None) -> float :
        """Converts a value to a voltage for a primary channel. 

        Args:
            value (int): Value to be converted to voltage.
            ssGain (int | None, optional): Second stage gain. Defaults to None.
            PreampGain (int | None, optional): Preamplifier gain. Defaults to None.

        Returns:
            float: Number of the voltage in volts [V]. Returns value if no gain is given (no-connect).
        """
        if(ssGain != None and PreampGain == None) : 
            return(PacketBinary5._Voltage_PrimaryChannels_Biosensor(value, ssGain))
        elif(ssGain != None):
            return(PacketBinary5._Voltage_PrimaryChannels_EEGEMG(value, ssGain, PreampGain))
        else: 
            return(value) # no connect! this is noise 

    @staticmethod
    def _Voltage_PrimaryChannels_EEGEMG(value: int, ssGain: int, PreampGain: int) -> float : 
        """Converts a value to a voltage for an EEG/EMG primary channel. 

        Args:
            value (int): Value to be converted to voltage.
            ssGain (int): Second stage gain.
            PreampGain (int): Preamplifier gain.

        Returns:
            float: Number of the voltage in volts [V].
        """
        # Channels configured as EEG/EMG channels (0.4/1/10 Hz highpass filter, second stage 0.5Hz Highpass, second stage 5x)
        voltageAtADC = (value / 262144.0) * 4.096 # V
        totalGain    = 10.0 * ssGain * PreampGain # SSGain = 1 or 5, PreampGain = 10 or 100
        realVoltage  = (voltageAtADC - 2.048) / totalGain # V
        return(realVoltage)

    @staticmethod
    def _Voltage_PrimaryChannels_Biosensor(value: int, ssGain: int) -> float : 
        """Converts a value to a voltage for a biosensor primary channel. 

        Args:
            value (int): Value to be converted to voltage.
            ssGain (int): Second stage gain.

        Returns:
            float: Number of the voltage in volts [V]. 
        """
        # Channels configured as biosensor channels (DC highpass filter, second stage DC mode, second stage 1x)
        voltageAtADC = (value / 262144.0) * 4.096 # V
        totalGain    = 1.557 * ssGain * 1E7 # SSGain = 1 or 5
        realVoltage  = (voltageAtADC - 2.048) / totalGain # V
        return(realVoltage)

    @staticmethod
    def _Voltage_SecondaryChannels(value: int) -> float :
        """Converts a value to a voltage for a secondary channel.

        Args:
            value (int): Value to be converted to voltage.

        Returns:
            float: Number of the voltage in volts [V].
        """
        # The additional inputs (EXT0, EXT1, TTL1-3) values are all 12-bit referenced to 3.3V.  To convert them to real voltages, the formula is as follows
        return( (value / 4096.0) * 3.3 ) # V
