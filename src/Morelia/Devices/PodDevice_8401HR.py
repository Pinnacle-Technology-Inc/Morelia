# local imports 
from Morelia.Devices import AcquisitionDevice, Pod, Preamp
from Morelia.packet import ControlPacket, PrimaryChannelMode, SecondaryChannelMode
from Morelia.packet.data import DataPacket8401HR
import Morelia.packet.conversion as conv
import Morelia.packet.legacy.Packet as Packet

from functools import partial
from typing import Union

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Pod8401HR(AcquisitionDevice) : 
    """
    Pod8401HR handles communication using an 8401HR POD device. 

    :param port: Serial port to be opened. Used when initializing the COM_io instance.
    :param preamp: Device/sensor connected to the the 8401HR.
    :param primary_channel_mode: A tuple containing the mode of operation for each primary channel (EEG/EMG or Biosensor).
    :param secondary_channel_modes: A tuple containing the mode of operation for each secondary (TTL/AEXT) channel (analog or digital).
    :param ss_gain: Tuple storing the second-stage gain for all four channels. Defaults to ``(None, None, None, None)``.
    :param preamp_gain: Tuple storing the pramplifier gain for all four channels. Defaults to ``(None, None, None, None)``.
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
                 ss_gain: tuple[int|None]=(None, None, None, None), 
                 preamp_gain: tuple[int|None]=(None, None, None, None), 
                 baudrate:int=9600,
                 device_name: str | None = None
                ) -> None :
        """Runs when an instance is constructed. It runs the parent's initialization. Then it updates \
        the _commands to contain the appropriate commands for an 8401HR POD device. Sets the _ss_gain \
        and _preamp_gain.
        """

             # initialize POD_Basics
        super().__init__(port, 10000, baudrate=baudrate, device_name=device_name) 

        # set preamp.
        self._preamp: Preamp = preamp

        # get constants for adding commands 
        UINT8  = Pod.get_u(8)
        UINT16 = Pod.get_u(16)
        BINARY_5  = 23

        # remove unimplemented commands 
        self._commands.remove_command(5)  # STATUS
        self._commands.remove_command(10) # SAMPLE RATE
        self._commands.remove_command(11) # BINARY

        # add device specific commands
        self._commands.add_command( 100, 'GET SAMPLE RATE',      (0,),       (UINT16,),    False,   'Gets the current sample rate of the system, in Hz.')
        self._commands.add_command( 101, 'SET SAMPLE RATE',      (UINT16,),     (0,),      False,   'Sets the sample rate of the system, in Hz. Valid values are 100 - 2000 currently.')
        self._commands.add_command( 102,	'GET HIGHPASS',	    (UINT8,),	    (UINT8,),      False,  'Reads the highpass filter value for a channel. Requires the channel to read, returns 0-3, 0 = 0.5Hz, 1 = 1Hz, 2 = 10Hz, 3 = DC / No Highpass.')
        self._commands.add_command( 103,	'SET HIGHPASS',	    (UINT8, UINT8),	(0,),       False,  'Sets the highpass filter for a channel. Requires channel to set, and filter value. Values are the same as returned in GET HIGHPASS.')
        self._commands.add_command( 104,	'GET LOWPASS',	    (UINT8,),	    (UINT16,),     False,  'Gets the lowpass filter for the desired channel. Requires the channel to read, Returns the value in Hz.')
        self._commands.add_command( 105,	'SET LOWPASS',	    (UINT8, UINT16),	(0,),       False,  'Sets the lowpass filter for the desired channel to the desired value (21 - 15000) in Hz. Requires the channel to read, and value in Hz.')
        self._commands.add_command( 106,	'GET DC MODE',	    (UINT8,),	    (UINT8,),      False,  'Gets the DC mode for the channel. Requires the channel to read, returns the value 0 = Subtract VBias, 1 = Subtract AGND. Typically 0 for Biosensors, and 1 for EEG/EMG.')
        self._commands.add_command( 107,	'SET DC MODE',	    (UINT8, UINT8),	(0,),       False,  'Sets the DC mode for the selected channel. Requires the channel to read, and value to set. Values are the same as in GET DC MODE.')
        self._commands.add_command( 112,	'GET BIAS',	        (UINT8,),	    (UINT16,),     False,  'Gets the bias on a given channel. Returns the DAC value as a 16-bit 2\'s complement value, representing a value from +/- 2.048V.')
        self._commands.add_command( 113,	'SET BIAS',	        (UINT8, UINT16),	(0,),       False,  'Sets the bias on a given channel. Requires the channel and DAC value as specified in GET BIAS. Note that for most preamps, only channel 0/A DAC values are used. This can cause issues with bias subtraction on preamps with multiple bio chanenls.')
        self._commands.add_command( 114,	'GET EXT0 VALUE',   (0,),	    (UINT16,),     False,  'Reads the analog value on the EXT0 pin. Returns an unsigned 12-bit value, representing a 3.3V input. This is normally used to identify preamps.  Note that this function takes some time and blocks, so it should not be called during data acquisition if possible.')
        self._commands.add_command( 115,	'GET EXT1 VALUE',   (0,),	    (UINT16,),     False,  'Reads the analog value on the EXT1 pin. Returns an unsigned 12-bit value, representing a 3.3V input. This is normally used to identify if an 8480 is present.  Similar caveat re blocking as GET EXT0 VALUE.')
        self._commands.add_command( 116,	'SET EXT0',	        (UINT8,),	    (0,),       False,  'Sets the digital value of EXT0, 0 or 1.')
        self._commands.add_command( 117,	'SET EXT1',	        (UINT8,),	    (0,),       False,  'Sets the digital value of EXT1, 0 or 1.')
        self._commands.add_command( 121,	'SET INPUT GROUND', (UINT8,),	    (0,),       False,  'Sets whether channel inputs are grounded or connected to the preamp. Bitfield, bits 0-3, high nibble should be 0s. 0=Grounded, 1=Connected to Preamp.')
        self._commands.add_command( 122,	'GET INPUT GROUND', (0,),	    (UINT8,),      False,  'Returns the bitmask value from SET INPUT GROUND.')
        self._commands.add_command( 127,	'SET TTL CONFIG',   (UINT8, UINT8),	(0,),       False,  'Configures the TTL pins. First argument is output setup, 0 is open collector and 1 is push-pull. Second argument is input setup, 0 is analog and 1 is digital. Bit 7 = EXT0, bit 6 = EXT1, bits 4+5 unused, bits 0-3 TTL pins.')
        self._commands.add_command( 128,	'GET TTL CONFIG',   (0,),	    (UINT8, UINT8),   False,  'Gets the TTL config byte, values are as per SET TTL CONFIG.')
        self._commands.add_command( 129,	'SET TTL OUTS',	    (UINT8, UINT8),	(0,),       False,  'Sets the TTL pins.  First byte is a bitmask, 0 = do not modify, 1=modify. Second byte is bit field, 0 = low, 1 = high.')
        self._commands.add_command( 130,	'GET SS CONFIG',    (UINT8,),	    (UINT8,),      False,  'Gets the second stage gain config. Requires the channel and returins a bitfield. Bit 0 = 0 for 0.5Hz Highpass, 1 for DC Highpass. Bit 1 = 0 for 5x gain, 1 for 1x gain.')
        self._commands.add_command( 131,	'SET SS CONFIG',    (UINT8, UINT8),	(0,),       False,  'Sets the second stage gain config. Requires the channel and a config bitfield as per GET SS CONFIG.')
        self._commands.add_command( 132,	'SET MUX MODE',	    (UINT8,),	    (0,),       False,  'Sets mux mode on or off.  This causes EXT1 to toggle periodically to control 2BIO 3EEG preamps.  0 = off, 1 = on.')
        self._commands.add_command( 133,	'GET MUX MODE',	    (0,),	    (UINT8,),      False,  'Gets the state of mux mode. See SET MUX MODE.')
        self._commands.add_command( 134,	'GET TTL ANALOG',   (UINT8,),	    (UINT16,),     False,  'Reads a TTL input as an analog signal. Requires a channel to read, returns a 10-bit analog value. Same caveats and restrictions as GET EXTX VALUE commands. Normally you would just enable an extra channel in Sirenia for this.')
        self._commands.add_command( 181, 'BINARY5 DATA',     (0,),	    (BINARY_5,),      True,   'Binary5 data packets, enabled by using the STREAM command with a \'1\' argument.')


        # so, currently we do this weird thing where we turn tuples into
        # dictionaries for preamp and ss gains. we shouldnt do this, but do it right now as an artifact of legacy code. please remove this
        # at some point as this class containes to be rewritten.

        # set second stage gain.
        ss_gain_dict = self._fix_abcd_type(ss_gain, this_is='ss_gain ')
        self._validate_ss_gain(ss_gain_dict)
        self._ss_gain : dict[str,int|None] = ss_gain_dict         

        preamp_gain_dict = self._fix_abcd_type(preamp_gain, this_is='preamp_gain')
        self._validate_preamp_gain(preamp_gain_dict)
        self._preamp_gain : dict[str,int|None] = preamp_gain_dict
        
        # set channel modes.
        self._primary_channel_modes = primary_channel_modes
        self._secondary_channel_modes = secondary_channel_modes
        
        # function used for constructing packets from stream data.
        self._stream_packet_factory = partial(DataPacket8401HR, preamp_gain, ss_gain, self._primary_channel_modes, self._secondary_channel_modes)
        
        # define function used for decoding the payloads of control packets and returning the proper responses.
        def decode_payload(command_number: int, payload: bytes) -> tuple:
            if command_number == 127 | 128 | 129:
                return Pod8401HR.decode_ttl_payload(payload)
            return ControlPacket.decode_payload_from_cmd_set(self._commands, command_number, payload)
        
        # the constructor used to create control packets as they are recieved.
        self._control_packet_factory = partial(ControlPacket, decode_payload)
    
    @property
    def preamp(self) -> Preamp:
        """Preamp connected to device."""
        return self._preamp

    @staticmethod
    def _fix_abcd_type(info: tuple|list|dict, this_is: str = '') -> dict : 
        """Converts the info argument into a dictionary with A, B, C, and D as keys.

        :param info: Variable to be converted into a dictionary. 
        :param this_is: Description of the info argument, which is used in Exception statements. Defaults to ''.

        :return: The info argument converted to a dictionary with A, B, C, and D as keys.  
        """
        # check for dict type 
        if(isinstance(info, dict)) : 
            # check keys
            if(list(info.keys()).sort() != ['A','B','C','D'].sort()) : 
                raise Exception('[!] The '+str(this_is)+'dictionary has improper keys; keys must be [\'A\',\'B\',\'C\',\'D\'].')        
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
            raise Exception('[!] The '+str(this_is)+'argument must have only four values.') 
        raise Exception('[!] The '+str(this_is)+'argument must be a tuple, list, or dict.')
    

    @staticmethod
    def _validate_ss_gain(ssgain: dict) -> None: 
        """Checks that the second stage gain dictionary has proper values (1, 5, or None). Otherwise raises exception.

        :param ssgain: Second stage gain dictionary.
        """
        for value in ssgain.values() :
            # both biosensors and EEG/EMG have ss_gain. None when no connect 
            if(value != 1 and value != 5 and value != None): 
                raise Exception('[!] The ss_gain must be 1 or 5; set ss_gain to None if no-connect.')
            
    @staticmethod
    def _validate_preamp_gain(preamp_gain: dict) -> None:
        """Checks that the preamplifier gain dictionary has proper values (10, 100, or None). Otherwise raises exception.

        :param preamp_gain: preamplifier gain dictionary.
        """
        for value in preamp_gain.values() :
            # None when biosensor or no connect 
            if(value != 10 and value != 100 and value != None): 
                raise Exception('[!] EEG/EMG preamp_gain must be 10 or 100. For biosensors, the preamp_gain is None.')
            
            
    @staticmethod
    def get_channel_map_for_preamp_device(preamp_name: Preamp) -> dict[str,str]|None :
        """Get the channel mapping (channel labels for A,B,C,D) for a given device.

        :param preamp_name: Device/sensor for lookup.

        :return: Dictionary with keys A,B,C,D with values of the channel names. Returns None if the device name does not exist.
        """
        if(preamp_name in Pod8401HR.__CHANNELMAPALL) : 
            return(Pod8401HR.__CHANNELMAPALL[preamp_name])
        else : 
            return(None) # no device matched



    @staticmethod
    def get_ttl_bitmask(ext0:int=0, ext1:int=0, ttl4:int=0, ttl3:int=0, ttl2:int=0, ttl1:int=0) -> int :
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
    def decode_ttl_payload(payload: bytes) -> tuple[dict[str, int]] : 
        """Decodes a paylaod with the two TTL bytes.

        :param payload: Bytes string of the POD packet payload.

        :return: Tuple with two TTL dictionaries.
        """
        return ( Pod8401HR.decode_ttl_byte(payload[:2]), Pod8401HR.decode_ttl_byte(payload[2:]))


    @staticmethod
    def decode_ttl_byte(ttl_byte: bytes) -> dict[str,int] : 
        """Converts the TTL bytes argument into a dictionary of integer TTL values.

        :param ttl_byte: UINT8 byte containing the TTL bitmask. 

        :return: Dictinoary with TTL name keys and integer TTL values. 
        """

        return({
            'EXT0' : conv.ascii_bytes_to_int_split(ttl_byte, 8, 7),
            'EXT1' : conv.ascii_bytes_to_int_split(ttl_byte, 7, 6),
            'TTL4' : conv.ascii_bytes_to_int_split(ttl_byte, 4, 3),
            'TTL3' : conv.ascii_bytes_to_int_split(ttl_byte, 3, 2),
            'TTL2' : conv.ascii_bytes_to_int_split(ttl_byte, 2, 1),
            'TTL1' : conv.ascii_bytes_to_int_split(ttl_byte, 1, 0)
        })
    

    @staticmethod
    def get_ss_config_bitmask(gain: int, highpass: float) -> int :
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
    def decode_ss_config_bitmask(config: bytes) -> dict[str, Union[float,int]]: 
        """Converts the SS configuration byte to a dictionary with the high-pass and gain. Use for ``GET SS CONFIG`` command payloads.

        :param config: UINT8 byte containing the SS configurtation. Bit 0 = 0 for 0.5Hz Highpass, 1 for DC Highpass. Bit 1 = 0 for 5x gain, 1 for 1x gain.
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
    def get_channel_bitmask(a: bool, b: bool, c: bool, d: bool) -> int :
        """Gets a bitmask, represented by an unsigned integer, used for ``SET INPUT GROUND`` command. 

            :param a: State for channel A, 0=Grounded and 1=Connected to Preamp.
            :param b: State for channel B, 0=Grounded and 1=Connected to Preamp.
            :param c: State for channel C, 0=Grounded and 1=Connected to Preamp.
            :param d: State for channel D, 0=Grounded and 1=Connected to Preamp.

            :return: Integer representing a bitmask.
        """
        return( 0 | (d << 3) | (c << 2) | (b << 1) | a )


    @staticmethod
    def decode_channel_bitmask(channels: bytes) -> dict[str,int] :
        """Converts the channel bitmask byte to a dictionary with each channel value. Use for ``GET INPUT GROUND`` command payloads.

        :param channels: UINT8 byte containing the channel configuration. 

        :return: Dictionary with the channels as keys and values as the state. 0=Grounded and 1=Connected to Preamp.
        """
        return({
            'A' : conv.ascii_bytes_to_int_split(channels, 4, 3),
            'B' : conv.ascii_bytes_to_int_split(channels, 3, 2),
            'C' : conv.ascii_bytes_to_int_split(channels, 2, 1),
            'D' : conv.ascii_bytes_to_int_split(channels, 1, 0)
        })



    @staticmethod
    def calculate_bias_dac_get_vout(value: int) -> float :
        """Calculates the output voltage given the DAC value. Used for ``GET/SET BIAS`` commands. 

        :param value: DAC value (16 bit 2's complement).

        :return: Float of the output bias voltage [V].
        """
        # Use this method for GET/SET BIAS commands 
        # DAC Value is 16 Bits 2's complement (aka signed) corresponding to the output bias voltage 
        return( (value / 32768.) * 2.048 )


    @staticmethod
    def calculate_bias_dac_get_dac_value(vout: int|float) -> int :
        """Calculates the DAC value given the output voltage. Used for ``GET/SET BIAS`` commands. 

        :param vout: Output voltage (+/- 2.048 V).

        :return: Integer of the DAC value (16 bit 2's complement).
        """
        # Use this method for GET/SET BIAS commands 
        # DAC Value is 16 Bits 2's complement (aka signed) corresponding to the output bias voltage 
        return(int( (vout / 2.048) * 32768. ))
        

    def _read_binary(self, pre_packet: bytes, validate_checksum:bool=True) -> DataPacket8401HR:
        """After receiving the pre_packet, it reads the 23 bytes (binary data) and then reads to ETX. See documentation of DataPacket8401HR 
        for what the recieved packet looks like on a binary level.

        :param pre_packet: Bytes string containing the beginning of a POD packet: STX (1 byte) + command number (4 bytes).
        :param validate_checksum: Set to True to validate the checksum. Set to False to skip validation. Defaults to True.

        :return: Packet recieved from device.
        """
        
        # get prepacket (STX+command number) (5 bytes) + 23 binary bytes (do not search for STX/ETX) + read csm and ETX (3 bytes) (these are ASCII, so check for STX/ETX)
        packet = pre_packet + self._port.read(23) + self._read_to_etx(validate_checksum=validate_checksum)
        # check if checksum is correct 
        if(validate_checksum):
            if(not self._validate_checksum(packet) ) :
                raise Exception('Bad checksum for binary POD packet read.')
        # return complete variable length binary packet
        return self._stream_packet_factory(packet)
 
