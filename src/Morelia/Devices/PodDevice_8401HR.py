# local imports 
from Morelia.Devices import AquisitionDevice, Pod, Preamp
from Morelia.packet import ControlPacket, PrimaryChannelMode, SecondaryChannelMode
from Morelia.packet.data import DataPacket8401HR

from functools import partial
from typing import Union

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Pod8401HR(AquisitionDevice) : 
    """
    Pod8401HR handles communication using an 8401HR POD device. 

    :param port: Serial port to be opened. Used when initializing the COM_io instance.
    :param preamp: Device/sensor connected to the the 8401HR.
    :param primary_channel_mode: A tuple containing the mode of operation for each primary channel (EEG/EMG or Biosensor).
    :param secondary_channel_modes: A tuple containing the mode of operation for each secondary (TTL/AEXT) channel (analog or digital).
    :param ssGain: Dictionary storing the second-stage gain for all four channels. Defaults to ``{'A':None,'B':None,'C':None,'D':None}``.
    :param preampGain: Dictionary storing the pramplifier gain for all four channels. Defaults to ``{'A':None,'B':None,'C':None,'D':None}``.
    :param baudrate: Integer baud rate of the opened serial port. Used when initializing the COM_io instance. Defaults to 9600.
    :param device_name: Virtual name used to indentify device.
    """

    # Class-level dictionary containing the channel map for all preamplifier devices.
    __CHANNELMAPALL : dict[Preamp,dict[str,str]] = {
        Preamp.Preamp8407_SE      : {'A':'Bio' , 'B':'EEG1', 'C':'EMG' , 'D':'EEG2'},
        Preamp.Preamp8407_SL      : {'A':'Bio' , 'B':'EEG1', 'C':'EMG' , 'D':'EEG2'},
        Preamp.Preamp8407_SE3     : {'A':'Bio' , 'B':'EEG1', 'C':'EEG3', 'D':'EEG2'},
        Preamp.Preamp8407_SE4     : {'A':'EEG4', 'B':'EEG1', 'C':'EEG3', 'D':'EEG2'},
        Preamp.Preamp8407_SE31M   : {'A':'EEG3', 'B':'EEG1', 'C':'EMG' , 'D':'EEG2'},
        Preamp.Preamp8407_SE_2BIO : {'A':'Bio1', 'B':'Bio2', 'C':'EMG' , 'D':'EEG2'},
        Preamp.Preamp8407_SL_2BIO : {'A':'Bio1', 'B':'Bio2', 'C':'EMG' , 'D':'EEG2'},
        Preamp.Preamp8406_SE31M   : {'A':'EMG' , 'B':'EEG1', 'C':'EEG3', 'D':'EEG2'},
        Preamp.Preamp8406_BIO     : {'A':'Bio' , 'B':'NC'  , 'C':'NC'  , 'D':'NC'  },
        Preamp.Preamp8406_2BIO    : {'A':'Bio1', 'B':'Bio2', 'C':'NC'  , 'D':'NC'  },
        Preamp.Preamp8406_EEG2BIO : {'A':'Bio1', 'B':'EEG1', 'C':'EMG' , 'D':'Bio2'},
        Preamp.Preamp8406_SE      : {'A':'Bio' , 'B':'EEG1', 'C':'EMG' , 'D':'EEG2'},
        Preamp.Preamp8406_SL      : {'A':'Bio' , 'B':'EEG1', 'C':'EMG' , 'D':'EEG2'},
        Preamp.Preamp8406_SE3     : {'A':'Bio' , 'B':'EEG1', 'C':'EEG3', 'D':'EEG2'},
        Preamp.Preamp8406_SE4     : {'A':'EEG4', 'B':'EEG1', 'C':'EEG3', 'D':'EEG2'}
    }

    def __init__(self, 
                 port: str|int, 
                 preamp: Preamp,
                 primary_channel_modes: tuple[PrimaryChannelMode] ,
                 secondary_channel_modes: tuple[SecondaryChannelMode],
                 ssGain: tuple|list|dict[str,int|None]={'A':None,'B':None,'C':None,'D':None}, 
                 preampGain: tuple|list|dict[str,int|None]={'A':None,'B':None,'C':None,'D':None}, 
                 baudrate:int=9600,
                 device_name: str | None = None
                ) -> None :
        """Runs when an instance is constructed. It runs the parent's initialization. Then it updates \
        the _commands to contain the appropriate commands for an 8401HR POD device. Sets the _ssGain \
        and _preampGain.
        """

             # initialize POD_Basics
        super().__init__(port, 10000, baudrate=baudrate, device_name=device_name) 

        # set preamp.
        self._preamp: Preamp = preamp

        # get constants for adding commands 
        U8  = Pod.GetU(8)
        U16 = Pod.GetU(16)
        B5  = 23

        # remove unimplemented commands 
        self._commands.RemoveCommand(5)  # STATUS
        self._commands.RemoveCommand(10) # SAMPLE RATE
        self._commands.RemoveCommand(11) # BINARY

        # add device specific commands
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

        # set second stage gain.
        ssGain_dict = self._FixABCDtype(ssGain, thisIs='ssGain ')
        self._ValidateSsGain(ssGain_dict)
        self._ssGain : dict[str,int|None] = ssGain_dict         

        # set preamplifier gain.
        preampGain_dict = self._FixABCDtype(preampGain, thisIs='preampGain')
        self._ValidatePreampGain(preampGain_dict)
        self._preampGain : dict[str,int|None] = preampGain_dict
        
        # set channel modes.
        self._primary_channel_modes = primary_channel_modes
        self._secondary_channel_modes = secondary_channel_modes
        
        # function used for constructing packets from stream data.
        self._stream_packet_factory = partial(DataPacket8401HR, preampGain, ssGain, self._primary_channel_modes, self._secondary_channel_modes)
        
        # define function used for decoding the payloads of control packets and returning the proper responses.
        def decode_payload(command_number: int, payload: bytes) -> tuple:
            if command_number in 127 | 128 | 129:
                return Pod8401HR.DecodeTTLPayload(payload)
            return ControlPacket.decode_payload_from_cmd_set(self._commands, command_number, payload)
        
        # the constructor used to create control packets as they are recieved.
        self._control_packet_factory = partial(ControlPacket, decode_payload)
    
    @property
    def preamp(self) -> Preamp:
        """Preamp connected to device."""
        return self._preamp

    @staticmethod
    def _FixABCDtype(info: tuple|list|dict, thisIs: str = '') -> dict : 
        """Converts the info argument into a dictionary with A, B, C, and D as keys.

        :param info: Variable to be converted into a dictionary. 
        :param thisIs: Description of the info argument, which is used in Exception statements. Defaults to ''.

        :return: The info argument converted to a dictionary with A, B, C, and D as keys.  
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
    def _ValidateSsGain(ssgain: dict) -> None: 
        """Checks that the second stage gain dictionary has proper values (1, 5, or None). Otherwise raises exception.

        :param ssgain: Second stage gain dictionary.
        """
        for value in ssgain.values() :
            # both biosensors and EEG/EMG have ssGain. None when no connect 
            if(value != 1 and value != 5 and value != None): 
                raise Exception('[!] The ssGain must be 1 or 5; set ssGain to None if no-connect.')
            
    @staticmethod
    def _ValidatePreampGain(preampGain: dict) -> None:
        """Checks that the preamplifier gain dictionary has proper values (10, 100, or None). Otherwise raises exception.

        :param preampGain: preamplifier gain dictionary.
        """
        for value in preampGain.values() :
            # None when biosensor or no connect 
            if(value != 10 and value != 100 and value != None): 
                raise Exception('[!] EEG/EMG preampGain must be 10 or 100. For biosensors, the preampGain is None.')
            
            
    @staticmethod
    def GetChannelMapForPreampDevice(preampName: Preamp) -> dict[str,str]|None :
        """Get the channel mapping (channel labels for A,B,C,D) for a given device.

        :param preampName: Device/sensor for lookup.

        :return: Dictionary with keys A,B,C,D with values of the channel names. Returns None if the device name does not exist.
        """
        if(preampName in Pod8401HR.__CHANNELMAPALL) : 
            return(Pod8401HR.__CHANNELMAPALL[preampName])
        else : 
            return(None) # no device matched



    @staticmethod
    def GetTTLbitmask(ext0:int=0, ext1:int=0, ttl4:int=0, ttl3:int=0, ttl2:int=0, ttl1:int=0) -> int :
        """Builds an integer, which represents a binary mask, that can be used for TTL command arguments.

        :param ext0: boolean bit for ext0. Defaults to 0.
        :param ext1: boolean bit for ext1. Defaults to 0.
        :param ttl4: boolean bit for ttl4. Defaults to 0.
        :param ttl3: boolean bit for ttl3. Defaults to 0.
        :param ttl2: boolean bit for ttl2. Defaults to 0.
        :param ttl1: boolean bit for ttl1. Defaults to 0.

        :return: Integer number to be used as a bit mask.
        """
        # use this for the argument/return for TTL-specific commands 
        # (msb) Bit 7 = EXT0, bit 6 = EXT1, bits 4+5 unused, bits 0-3 TTL pins (lsb) 
        return( 0 | (ext0 << 7) | (ext1 << 6) | (ttl4 << 3) | (ttl3 << 2) | (ttl2 << 1) | ttl1 )


    @staticmethod
    def DecodeTTLPayload(payload: bytes) -> tuple[dict[str, int]] : 
        """Decodes a paylaod with the two TTL bytes.

        :param payload: Bytes string of the POD packet payload.

        :return: Tuple with two TTL dictionaries.
        """
        return ( Pod8401HR.DecodeTTLByte(payload[:2]), Pod8401HR.DecodeTTLByte(payload[2:]))


    @staticmethod
    def DecodeTTLByte(ttlByte: bytes) -> dict[str,int] : 
        """Converts the TTL bytes argument into a dictionary of integer TTL values.

        :param ttlByte: U8 byte containing the TTL bitmask. 

        :return: Dictinoary with TTL name keys and integer TTL values. 
        """

        return({
            'EXT0' : conv.ascii_bytes_to_int_split(ttlByte, 8, 7),
            'EXT1' : conv.ascii_bytes_to_int_split(ttlByte, 7, 6),
            'TTL4' : conv.ascii_bytes_to_int_split(ttlByte, 4, 3),
            'TTL3' : conv.ascii_bytes_to_int_split(ttlByte, 3, 2),
            'TTL2' : conv.ascii_bytes_to_int_split(ttlByte, 2, 1),
            'TTL1' : conv.ascii_bytes_to_int_split(ttlByte, 1, 0)
        })
    

    @staticmethod
    def GetSSConfigBitmask(gain: int, highpass: float) -> int :
        """Gets a bitmask, represented by an unsigned integer, used for ``SET SS CONFIG`` command. 

        :param gain: 1 for 1x gain. else for 5x gain. highpass (float): 0 for DC highpass, else for 0.5Hz highpass.

        :return: Integer representing a bitmask.
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
    def DecodeSSConfigBitmask(config: bytes) -> dict[str, Union[float,int]]: 
        """Converts the SS configuration byte to a dictionary with the high-pass and gain. Use for ``GET SS CONFIG`` command payloads.

        :param config: U8 byte containing the SS configurtation. Bit 0 = 0 for 0.5Hz Highpass, 1 for DC Highpass. Bit 1 = 0 for 5x gain, 1 for 1x gain.
        """
        # high-pass
        if(Packet.AsciiBytesToInt(config[0:1]) == 0) : 
            highpass = 0.5 # Bit 0 = 0 for 0.5Hz Highpass
        else: 
            highpass = 0.0 # Bit 0 = 1 for DC Highpass
        # gain 
        if(Packet.AsciiBytesToInt(config[1:2]) == 0) :
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
        """Gets a bitmask, represented by an unsigned integer, used for ``SET INPUT GROUND`` command. 

            :param a: State for channel A, 0=Grounded and 1=Connected to Preamp.
            :param b: State for channel B, 0=Grounded and 1=Connected to Preamp.
            :param c: State for channel C, 0=Grounded and 1=Connected to Preamp.
            :param d: State for channel D, 0=Grounded and 1=Connected to Preamp.

            :return: Integer representing a bitmask.
        """
        return( 0 | (d << 3) | (c << 2) | (b << 1) | a )


    @staticmethod
    def DecodeChannelBitmask(channels: bytes) -> dict[str,int] :
        """Converts the channel bitmask byte to a dictionary with each channel value. Use for ``GET INPUT GROUND`` command payloads.

        :param channels: U8 byte containing the channel configuration. 

        :return: Dictionary with the channels as keys and values as the state. 0=Grounded and 1=Connected to Preamp.
        """
        return({
            'A' : conv.ascii_bytes_to_int_split(channels, 4, 3),
            'B' : conv.ascii_bytes_to_int_split(channels, 3, 2),
            'C' : conv.ascii_bytes_to_int_split(channels, 2, 1),
            'D' : conv.ascii_bytes_to_int_split(channels, 1, 0)
        })



    @staticmethod
    def CalculateBiasDAC_GetVout(value: int) -> float :
        """Calculates the output voltage given the DAC value. Used for ``GET/SET BIAS`` commands. 

        :param value: DAC value (16 bit 2's complement).

        :return: Float of the output bias voltage [V].
        """
        # Use this method for GET/SET BIAS commands 
        # DAC Value is 16 Bits 2's complement (aka signed) corresponding to the output bias voltage 
        return( (value / 32768.) * 2.048 )


    @staticmethod
    def CalculateBiasDAC_GetDACValue(vout: int|float) -> int :
        """Calculates the DAC value given the output voltage. Used for ``GET/SET BIAS`` commands. 

        :param vout: Output voltage (+/- 2.048 V).

        :return: Integer of the DAC value (16 bit 2's complement).
        """
        # Use this method for GET/SET BIAS commands 
        # DAC Value is 16 Bits 2's complement (aka signed) corresponding to the output bias voltage 
        return(int( (vout / 2.048) * 32768. ))
        

    def _Read_Binary(self, prePacket: bytes, validateChecksum:bool=True) -> DataPacket8401HR:
        """After receiving the prePacket, it reads the 23 bytes (binary data) and then reads to ETX. See documentation of DataPacket8401HR 
        for what the recieved packet looks like on a binary level.

        :param prePacket: Bytes string containing the beginning of a POD packet: STX (1 byte) + command number (4 bytes).
        :param validateChecksum: Set to True to validate the checksum. Set to False to skip validation. Defaults to True.

        :return: Packet recieved from device.
        """
        
        # get prepacket (STX+command number) (5 bytes) + 23 binary bytes (do not search for STX/ETX) + read csm and ETX (3 bytes) (these are ASCII, so check for STX/ETX)
        packet = prePacket + self._port.Read(23) + self._Read_ToETX(validateChecksum=validateChecksum)
        # check if checksum is correct 
        if(validateChecksum):
            if(not self._ValidateChecksum(packet) ) :
                raise Exception('Bad checksum for binary POD packet read.')
        # return complete variable length binary packet
        return self._stream_packet_factory(packet)
 
