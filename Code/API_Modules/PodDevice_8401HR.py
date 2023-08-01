# local imports 
from BasicPodProtocol       import POD_Basics
from PodPacketHandling      import POD_Packets
from PodPacket_Packet       import Packet
from PodPacket_Standard     import Packet_Standard
from PodPacket_Binary5      import Packet_Binary5

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class POD_8401HR(POD_Basics) : 
    """
    POD_8401HR handles communication using an 8401-HR POD device. 

    Attributes:
        _ssGain (dict[str,int|None]): Instance-level dictionary storing the second-stage gain for all \
            four channels. 
        _preampGain (dict[str,int|None]): Instance-level dictionary storing the pramplifier gain for \
            all four channels. 
    """

    # ============ GLOBAL CONSTANTS ============    ========================================================================================================================

    __CHANNELMAPALL : dict[str,dict[str,str]] = {
        '8407-SE'      : {'A':'Bio' , 'B':'EEG1', 'C':'EMG' , 'D':'EEG2'},
        '8407-SL'      : {'A':'Bio' , 'B':'EEG1', 'C':'EMG' , 'D':'EEG2'},
        '8407-SE3'     : {'A':'Bio' , 'B':'EEG1', 'C':'EEG3', 'D':'EEG2'},
        '8407-SE4'     : {'A':'EEG4', 'B':'EEG1', 'C':'EEG3', 'D':'EEG2'},
        '8407-SE31M'   : {'A':'EEG3', 'B':'EEG1', 'C':'EMG' , 'D':'EEG2'},
        '8407-SE-2BIO' : {'A':'Bio1', 'B':'Bio2', 'C':'EMG' , 'D':'EEG2'},
        '8407-SL-2BIO' : {'A':'Bio1', 'B':'Bio2', 'C':'EMG' , 'D':'EEG2'},
        '8406-SE31M'   : {'A':'EMG' , 'B':'EEG1', 'C':'EEG3', 'D':'EEG2'},
        '8406-BIO'     : {'A':'Bio' , 'B':'NC'  , 'C':'NC'  , 'D':'NC'  },
        '8406-2BIO'    : {'A':'Bio1', 'B':'Bio2', 'C':'NC'  , 'D':'NC'  },
        '8406-EEG2BIO' : {'A':'Bio1', 'B':'EEG1', 'C':'EMG' , 'D':'Bio2'},
        '8406-SE'      : {'A':'Bio' , 'B':'EEG1', 'C':'EMG' , 'D':'EEG2'},
        '8406-SL'      : {'A':'Bio' , 'B':'EEG1', 'C':'EMG' , 'D':'EEG2'},
        '8406-SE3'     : {'A':'Bio' , 'B':'EEG1', 'C':'EEG3', 'D':'EEG2'},
        '8406-SE4'     : {'A':'EEG4', 'B':'EEG1', 'C':'EEG3', 'D':'EEG2'}
    }
    """Class-level dictionary containing the channel map for \
    all preamplifier devices.
    """

    # ============ METHODS ============      ========================================================================================================================
    
    # ------------ INITIALIZATION ------------           ------------------------------------------------------------------------------------------------------------------------

    def __init__(self, 
                 port: str|int, 
                 ssGain: tuple|list|dict[str,int|None]={'A':None,'B':None,'C':None,'D':None}, 
                 preampGain: tuple|list|dict[str,int|None]={'A':None,'B':None,'C':None,'D':None}, 
                 baudrate:int=9600
                ) -> None :
        """Runs when an instance is constructed. It runs the parent's initialization. Then it updates \
        the _commands to contain the appropriate commands for an 8401HR POD device. Sets the _ssGain \
        and _preampGain.

        Args:
            port (str | int): Serial port to be opened. Used when initializing the COM_io instance.
            preampName (str): String of the corresponding device/sensor name.
            ssGain (tuple|list|dict[str,int|None], optional): Dictionary storing the second-stage gain for all four \
                channels. Defaults to {'A':None,'B':None,'C':None,'D':None}.
            preampGain (tuple|list|dict[str,int|None], optional): Dictionary storing the pramplifier gain for all \
                four channels. Defaults to {'A':None,'B':None,'C':None,'D':None}.
            baudrate (int, optional): Integer baud rate of the opened serial port. Used when initializing \
                the COM_io instance. Defaults to 9600.
        """
        # initialize POD_Basics
        super().__init__(port, baudrate=baudrate) 
        # get constants for adding commands 
        U8  = POD_Basics.GetU(8)
        U16 = POD_Basics.GetU(16)
        B5  = Packet_Binary5.GetBinaryLength()
        # remove unimplemented commands 
        self._commands.RemoveCommand(5)  # STATUS
        self._commands.RemoveCommand(10) # SAMPLE RATE
        self._commands.RemoveCommand(11) # BINARY
        # add device specific commands
        self._commands.AddCommand( 100, 'GET SAMPLE RATE',  (0,),       (U16,),     False,  'Gets the current sample rate of the system, in Hz.')
        self._commands.AddCommand( 101, 'SET SAMPLE RATE',  (U16,),     (0,),       False,  'Sets the sample rate of the system, in Hz. Valid values are 2000 - 20000 currently.')
        self._commands.AddCommand( 102,	'GET HIGHPASS',	    (U8,),	    (U8,),      False,  'Reads the highpass filter value for a channel. Requires the channel to read, returns 0-3, 0 = 0.5Hz, 1 = 1Hz, 2 = 10Hz, 3 = DC / No Highpass.')
        self._commands.AddCommand( 103,	'SET HIGHPASS',	    (U8, U8),	(0,),       False,  'Sets the highpass filter for a channel. Requires channel to set, and filter value. Values are the same as returned in GET HIGHPASS.')
        self._commands.AddCommand( 104,	'GET LOWPASS',	    (U8,),	    (U16,),     False,  'Gets the lowpass filter for the desired channel. Requires the channel to read, Returns the value in Hz.')
        self._commands.AddCommand( 105,	'SET LOWPASS',	    (U8, U16),	(0,),       False,  'Sets the lowpass filter for the desired channel to the desired value (21 - 15000) in Hz. Requires the channel to read, and value in Hz.')
        self._commands.AddCommand( 106,	'GET DC MODE',	    (U8,),	    (U8,),      False,  'Gets the DC mode for the channel. Requires the channel to read, returns the value 0 = Subtract VBias, 1 = Subtract AGND. Typically 0 for Biosensors, and 1 for EEG/EMG.')
        self._commands.AddCommand( 107,	'SET DC MODE',	    (U8, U8),	(0,),       False,  'Sets the DC mode for the selected channel. Requires the channel to read, and value to set. Values are the same as in GET DC MODE.')
        self._commands.AddCommand( 112,	'GET BIAS',	        (U8,),	    (U16,),     False,  'Gets the bias on a given channel. Returns the DAC value as a 16-bit 2\'s complement value, representing a value from +/- 2.048V.')
        self._commands.AddCommand( 113,	'SET BIAS',	        (U8, U16),	(0,),       False,  'Sets the bias on a given channel. Requires the channel and DAC value as specified in GET BIAS. Note that for most preamps, only channel 0/A DAC values are used. This can cause issues with bias subtraction on preamps with multiple bio chanenls.')
        self._commands.AddCommand( 114,	'GET EXT0 VALUE',   (0,),	    (U16,),     False,  'Reads the analog value on the EXT0 pin. Returns an unsigned 12-bit value, representing a 3.3V input. This is normally used to identify preamps.  Note that this function takes some time and blocks, so it should not be called during data acquisition if possible.')
        self._commands.AddCommand( 115,	'GET EXT1 VALUE',   (0,),	    (U16,),     False,  'Reads the analog value on the EXT1 pin. Returns an unsigned 12-bit value, representing a 3.3V input. This is normally used to identify if an 8480 is present.  Similar caveat re blocking as GET EXT0 VALUE.')
        self._commands.AddCommand( 116,	'SET EXT0',	        (U8,),	    (0,),       False,  'Sets the digital value of EXT0, 0 or 1.')
        self._commands.AddCommand( 117,	'SET EXT1',	        (U8,),	    (0,),       False,  'Sets the digital value of EXT1, 0 or 1.')
        self._commands.AddCommand( 121,	'SET INPUT GROUND', (U8,),	    (0,),       False,  'Sets whether channel inputs are grounded or connected to the preamp. Bitfield, bits 0-3, high nibble should be 0s. 0=Grounded, 1=Connected to Preamp.')
        self._commands.AddCommand( 122,	'GET INPUT GROUND', (0,),	    (U8,),      False,  'Returns the bitmask value from SET INPUT GROUND.')
        self._commands.AddCommand( 127,	'SET TTL CONFIG',   (U8, U8),	(0,),       False,  'Configures the TTL pins. First argument is output setup, 0 is open collector and 1 is push-pull. Second argument is input setup, 0 is analog and 1 is digital. Bit 7 = EXT0, bit 6 = EXT1, bits 4+5 unused, bits 0-3 TTL pins.')
        self._commands.AddCommand( 128,	'GET TTL CONFIG',   (0,),	    (U8, U8),   False,  'Gets the TTL config byte, values are as per SET TTL CONFIG.')
        self._commands.AddCommand( 129,	'SET TTL OUTS',	    (U8, U8),	(0,),       False,  'Sets the TTL pins.  First byte is a bitmask, 0 = do not modify, 1=modify. Second byte is bit field, 0 = low, 1 = high.')
        self._commands.AddCommand( 130,	'GET SS CONFIG',    (U8,),	    (U8,),      False,  'Gets the second stage gain config. Requires the channel and returins a bitfield. Bit 0 = 0 for 0.5Hz Highpass, 1 for DC Highpass. Bit 1 = 0 for 5x gain, 1 for 1x gain.')
        self._commands.AddCommand( 131,	'SET SS CONFIG',    (U8, U8),	(0,),       False,  'Sets the second stage gain config. Requires the channel and a config bitfield as per GET SS CONFIG.')
        self._commands.AddCommand( 132,	'SET MUX MODE',	    (U8,),	    (0,),       False,  'Sets mux mode on or off.  This causes EXT1 to toggle periodically to control 2BIO 3EEG preamps.  0 = off, 1 = on.')
        self._commands.AddCommand( 133,	'GET MUX MODE',	    (0,),	    (U8,),      False,  'Gets the state of mux mode. See SET MUX MODE.')
        self._commands.AddCommand( 134,	'GET TTL ANALOG',   (U8,),	    (U16,),     False,  'Reads a TTL input as an analog signal. Requires a channel to read, returns a 10-bit analog value. Same caveats and restrictions as GET EXTX VALUE commands. Normally you would just enable an extra channel in Sirenia for this.')
        self._commands.AddCommand( 181, 'BINARY5 DATA',     (0,),	    (B5,),      True,   'Binary5 data packets, enabled by using the STREAM command with a \'1\' argument.')
        # second stage gain
        ssGain_dict = self._FixABCDtype(ssGain, thisIs='ssGain ')
        self._ValidateSsGain(ssGain_dict)
        self._ssGain : dict[str,int|None] = ssGain_dict         
        # preamplifier gain
        preampGain_dict = self._FixABCDtype(preampGain, thisIs='preampGain ')
        self._ValidatePreampGain(preampGain_dict)
        self._preampGain : dict[str,int|None] = preampGain_dict
    
    
    @staticmethod
    def _FixABCDtype(info: tuple|list|dict, thisIs: str = '') -> dict : 
        """Converts the info argument into a dictionary with A, B, C, and D as keys.

        Args:
            info (tuple | list | dict): Variable to be converted into a dictionary. 
            thisIs (str, optional): Description of the info argument, which is used in \
                Exception statements. Defaults to ''.

        Raises:
            Exception: The dictionary has improper keys; keys must be ['A','B','C','D'].
            Exception: The argument must have only four values.
            Exception: The argument must be a tuple, list, or dict.

        Returns:
            dict: The info argument converted to a dictionary with A, B, C, and D as keys.  
        """
        # check for dict type 
        if(isinstance(info, dict)) : 
            # check keys
            if(list(info.keys()).sort() != ['A','B','C','D'].sort()) : 
                raise Exception('[!] The '+str(thisIs)+'dictionary has improper keys; keys must be [\'A\',\'B\',\'C\',\'D\'].')        
            return info
        # check for array-like type 
        if(isinstance(info, tuple|list) ) : 
            # check size 
            if(len(info) == 4) : 
                # build dictionary 
                return {'A' : info[0],
                        'B' : info[1],
                        'C' : info[2],
                        'D' : info[3] }
            raise Exception('[!] The '+str(thisIs)+'argument must have only four values.') 
        raise Exception('[!] The '+str(thisIs)+'argument must be a tuple, list, or dict.')
    

    @staticmethod
    def _ValidateSsGain(ssgain: dict) : 
        """Checks that the second stage gain dictionary has proper values (1, 5, or None).

        Args:
            ssgain (dict): Second stage gain dictionary.

        Raises:
            Exception: The ssGain must be 1 or 5; set ssGain to None if no-connect.
        """
        for value in ssgain.values() :
            # both biosensors and EEG/EMG have ssGain. None when no connect 
            if(value != 1 and value != 5 and value != None): 
                raise Exception('[!] The ssGain must be 1 or 5; set ssGain to None if no-connect.')
            
    @staticmethod
    def _ValidatePreampGain(preampGain: dict) -> None:
        """Checks that the preamplifier gain dictionary has proper values (10, 100, or None).

        Args:
            preampGain (dict): preamplifier gain dictionary.

        Raises:
            Exception: EEG/EMG preampGain must be 10 or 100. For biosensors, the preampGain is None.
        """
        for value in preampGain.values() :
            # None when biosensor or no connect 
            if(value != 10 and value != 100 and value != None): 
                raise Exception('[!] EEG/EMG preampGain must be 10 or 100. For biosensors, the preampGain is None.')
            
            
    # ------------ MAPPING ------------           ------------------------------------------------------------------------------------------------------------------------
    

    @staticmethod
    def GetChannelMapForPreampDevice(preampName: str) -> dict[str,str]|None :
        """Get the channel mapping (channel labels for A,B,C,D) for a given device.

        Args:
            preampName (str): String for the device/sensor name.

        Returns:
            dict[str,str]|None: Dictionary with keys A,B,C,D with values of the channel names. Returns \
                None if the device name does not exist.
        """
        if(preampName in POD_8401HR.__CHANNELMAPALL) : 
            return(POD_8401HR.__CHANNELMAPALL[preampName])
        else : 
            return(None) # no device matched


    @staticmethod
    def GetSupportedPreampDevices() -> list[str]: 
        """Gets a list of device/sensor names used for channel mapping. 

        Returns:
            list[str]: List of string names of all supported sensors. 
        """
        return(list(POD_8401HR.__CHANNELMAPALL.keys()))


    @staticmethod
    def IsPreampDeviceSupported(name: str) -> bool : 
        """Checks if the argument exists in channel map for all preamp sensors. 

        Args:
            name (str): name of the device

        Returns:
            bool: True if the name exists in __CHANNELMAPALL, false otherwise.
        """
        return(name in POD_8401HR.__CHANNELMAPALL)    


    # ------------ BITMASKING ------------           ------------------------------------------------------------------------------------------------------------------------


    @staticmethod
    def GetTTLbitmask(ext0:bool=0, ext1:bool=0, ttl4:bool=0, ttl3:bool=0, ttl2:bool=0, ttl1:bool=0) -> int :
        """Builds an integer, which represents a binary mask, that can be used for TTL command arguments.

        Args:
            ext0 (bool, optional): boolean bit for ext0. Defaults to 0.
            ext1 (bool, optional): boolean bit for ext1. Defaults to 0.
            ttl4 (bool, optional): boolean bit for ttl4. Defaults to 0.
            ttl3 (bool, optional): boolean bit for ttl3. Defaults to 0.
            ttl2 (bool, optional): boolean bit for ttl2. Defaults to 0.
            ttl1 (bool, optional): boolean bit for ttl1. Defaults to 0.

        Returns:
            int: Integer number to be used as a bit mask.
        """
        # use this for the argument/return for TTL-specific commands 
        # (msb) Bit 7 = EXT0, bit 6 = EXT1, bits 4+5 unused, bits 0-3 TTL pins (lsb) 
        return( 0 | (ext0 << 7) | (ext1 << 6) | (ttl4 << 3) | (ttl3 << 2) | (ttl2 << 1) | ttl1 )


    @staticmethod
    def DecodeTTLPayload(payload: bytes) -> tuple[dict[str, int]] : 
        """Decodes a paylaod with the two TTL bytes.

        Args:
            payload (bytes): Bytes string of the POD packet payload.

        Returns:
            tuple[dict[str, int]]: Tuple with two TTL dictionaries.
        """
        return ( POD_8401HR.DecodeTTLByte(payload[:2]), POD_8401HR.DecodeTTLByte(payload[2:]))


    @staticmethod
    def DecodeTTLByte(ttlByte: bytes) -> dict[str,int] : 
        """Converts the TTL bytes argument into a dictionary of integer TTL values.

        Args:
            ttlByte (bytes): U8 byte containing the TTL bitmask. 

        Returns:
            dict[str,int]: Dictinoary with TTL name keys and integer TTL values. 
        """
        return({
            'EXT0' : POD_Packets.ASCIIbytesToInt_Split(ttlByte, 8, 7),
            'EXT1' : POD_Packets.ASCIIbytesToInt_Split(ttlByte, 7, 6),
            'TTL4' : POD_Packets.ASCIIbytesToInt_Split(ttlByte, 4, 3),
            'TTL3' : POD_Packets.ASCIIbytesToInt_Split(ttlByte, 3, 2),
            'TTL2' : POD_Packets.ASCIIbytesToInt_Split(ttlByte, 2, 1),
            'TTL1' : POD_Packets.ASCIIbytesToInt_Split(ttlByte, 1, 0)
        })
    

    @staticmethod
    def GetSSConfigBitmask(gain: int, highpass: float) -> int :
        """Gets a bitmask, represented by an unsigned integer, used for 'SET SS CONFIG' command. 

        Args:
            gain (int): 1 for 1x gain. else for 5x gain.
            highpass (float): 0 for DC highpass, else for 0.5Hz highpass.

        Returns:
            int: Integer representing a bitmask.
        """
        # interpret highpass (lsb)
        if(highpass == 0.0) :   bit0 = True  # DC highpass
        else:                   bit0 = False # AC 0.5Hz highpass 
        # interpret gain (msb)
        if(gain == 1) : bit1 = True  # 1x gain 
        else:           bit1 = False # 5x gain 
        # bit shifting to get integer bitmask
        return( 0 | (bit1 << 1) | bit0 ) # use for 'SET SS CONFIG' command

    
    @staticmethod
    def DecodeSSConfigBitmask(config: bytes) : 
        """Converts the SS configuration byte to a dictionary with the high-pass and gain. \
        Use for 'GET SS CONFIG' command payloads.

        Args:
            config (bytes): U8 byte containing the SS configurtation. Bit 0 = 0 for 0.5Hz Highpass, \
                1 for DC Highpass. Bit 1 = 0 for 5x gain, 1 for 1x gain.
        """
        # high-pass
        if(POD_Packets.AsciiBytesToInt(config[0:1]) == 0) : 
            highpass = 0.5 # Bit 0 = 0 for 0.5Hz Highpass
        else: 
            highpass = 0.0 # Bit 0 = 1 for DC Highpass
        # gain 
        if(POD_Packets.AsciiBytesToInt(config[1:2]) == 0) :
            gain = 5 # Bit 1 = 0 for 5x gain
        else : 
            gain = 1 # Bit 1 = 1 for 1x gain
        # pack values into dict 
        return({
            'High-pass' : highpass, 
            'Gain'      : gain
        })
        

    @staticmethod
    def GetChannelBitmask(a: bool, b: bool, c: bool, d: bool) -> int :
        """Gets a bitmask, represented by an unsigned integer, used for 'SET INPUT GROUND' command. 

        Args:
            a (bool): State for channel A, 0=Grounded and 1=Connected to Preamp.
            b (bool): State for channel B, 0=Grounded and 1=Connected to Preamp.
            c (bool): State for channel C, 0=Grounded and 1=Connected to Preamp.
            d (bool): State for channel D, 0=Grounded and 1=Connected to Preamp.

        Returns:
            int: Integer representing a bitmask.
        """
        return( 0 | (d << 3) | (c << 2) | (b << 1) | a )


    @staticmethod
    def DecodeChannelBitmask(channels: bytes) -> dict[str,int] :
        """Converts the channel bitmask byte to a dictionary with each channel value. \
        Use for 'GET INPUT GROUND' command payloads.

        Args:
            channels (bytes): U8 byte containing the channel configuration. 

        Returns:
            dict[str,int]: Dictionary with the channels as keys and values as the state. \
                0=Grounded and 1=Connected to Preamp.
        """
        return({
            'A' : POD_Packets.ASCIIbytesToInt_Split(channels, 4, 3),
            'B' : POD_Packets.ASCIIbytesToInt_Split(channels, 3, 2),
            'C' : POD_Packets.ASCIIbytesToInt_Split(channels, 2, 1),
            'D' : POD_Packets.ASCIIbytesToInt_Split(channels, 1, 0)
        })


    # ------------ CALCULATIONS ------------           ------------------------------------------------------------------------------------------------------------------------


    @staticmethod
    def CalculateBiasDAC_GetVout(value: int) -> float :
        """Calculates the output voltage given the DAC value. Used for 'GET/SET BIAS' commands. 

        Args:
            value (int): DAC value (16 bit 2's complement).

        Returns:
            float: Float of the output bias voltage [V].
        """
        # Use this method for GET/SET BIAS commands 
        # DAC Value is 16 Bits 2's complement (aka signed) corresponding to the output bias voltage 
        return( (value / 32768.) * 2.048 )


    @staticmethod
    def CalculateBiasDAC_GetDACValue(vout: int|float) -> int :
        """Calculates the DAC value given the output voltage. Used for 'GET/SET BIAS' commands. 

        Args:
            vout (int | float): Output voltage (+/- 2.048 V).

        Returns:
            int: Integer of the DAC value (16 bit 2's complement).
        """
        # Use this method for GET/SET BIAS commands 
        # DAC Value is 16 Bits 2's complement (aka signed) corresponding to the output bias voltage 
        return(int( (vout / 2.048) * 32768. ))
        

    # ------------ OVERWRITE ------------           ------------------------------------------------------------------------------------------------------------------------


    def WritePacket(self, cmd: str|int, payload:int|bytes|tuple[int|bytes]=None) -> Packet_Standard :
        """Builds a POD packet and writes it to the POD device. 

        Args:
            cmd (str | int): Command number.
            payload (int | bytes | tuple[int | bytes], optional): None when there is no payload. If there \
                is a payload, set to an integer value, bytes string, or tuple. Defaults to None.

        Returns:
            Packet_Standard: Packet that was written to the POD device.
        """
        # write
        packet: Packet_Standard = super().WritePacket(cmd, payload)
        # check for special packets
        specialCommands = [127, 129] # 127 SET TTL CONFIG # 129 SET TTL OUTS
        if(packet.CommandNumber() in specialCommands) : 
            packet.SetCustomPayload(POD_8401HR.DecodeTTLPayload, (packet.payload,))
        # returns packet object
        return packet
    
    
    def ReadPODpacket(self, validateChecksum: bool = True, timeout_sec: int | float = 5) -> Packet:
        """Reads a complete POD packet, either in standard or binary format, beginning with STX and \
        ending with ETX. Reads first STX and then starts recursion. 

        Args:
            validateChecksum (bool, optional): Set to True to validate the checksum. Set to False to \
                skip validation. Defaults to True.
            timeout_sec (int|float, optional): Time in seconds to wait for serial data. \
                Defaults to 5. 

        Returns:
            Packet: POD packet beginning with STX and ending with ETX. This may be a \
                standard packet, binary packet, or an unformatted packet (STX+something+ETX). 
        """
        packet: Packet = super().ReadPODpacket(validateChecksum, timeout_sec)
        # check for special packets
        if(isinstance(packet, Packet_Standard)) : 
            if(packet.CommandNumber() == 128) : # 128 GET TTL CONFIG
                packet.SetCustomPayload(POD_8401HR.DecodeTTLPayload, (packet.payload,))
        # return packet
        return packet


    def _Read_Binary(self, prePacket: bytes, validateChecksum:bool=True) :
        """After receiving the prePacket, it reads the 23 bytes (binary data) and then reads to ETX. 

        Args:
            prePacket (bytes): Bytes string containing the beginning of a POD packet: STX (1 byte) \
                + command number (4 bytes).
            validateChecksum (bool, optional): Set to True to validate the checksum. Set to False to \
                skip validation. Defaults to True.

        Raises:
            Exception: Bad checksum for binary POD packet read.
        """
        
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

        # get prepacket (STX+command number) (5 bytes) + 23 binary bytes (do not search for STX/ETX) + read csm and ETX (3 bytes) (these are ASCII, so check for STX/ETX)
        packet = prePacket + self._port.Read(Packet_Binary5.GetBinaryLength()) + self._Read_ToETX(validateChecksum=validateChecksum)
        # check if checksum is correct 
        if(validateChecksum):
            if(not self._ValidateChecksum(packet) ) :
                raise Exception('Bad checksum for binary POD packet read.')
        # return complete variable length binary packet
        return Packet_Binary5(packet, self._ssGain, self._preampGain, self._commands)
 