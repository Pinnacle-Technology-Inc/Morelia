# local imports 
from Morelia.Devices import AcquisitionDevice, Pod, Preamp
from Morelia.Devices.preamp_config import lookup_preamp_config, ChannelConfig
from Morelia.packet import ControlPacket, PodPacket, PrimaryChannelMode, SecondaryChannelMode
from Morelia.packet.data import DataPacket8401HR
import Morelia.packet.conversion as conv
import Morelia.packet.legacy.Packet as Packet

from functools import partial
from typing import Union


def _deep_merge(base: dict, override: dict) -> None:
    """Merge *override* into *base* in-place.  Override values win for
    leaf keys; nested dicts are merged recursively."""
    for key, val in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            _deep_merge(base[key], val)
        else:
            base[key] = val

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
                 device_name: str | None = None,
                 use_d2xx: bool = False
                ) -> None :
        """Runs when an instance is constructed. It runs the parent's initialization. Then it updates \
        the _commands to contain the appropriate commands for an 8401HR POD device. Sets the _ss_gain \
        and _preamp_gain.
        """

             # initialize POD_Basics
        super().__init__(port, 10000, baudrate=baudrate, device_name=device_name, use_d2xx=use_d2xx) 

        # set preamp.
        self._preamp: Preamp = preamp
        self._ss_gain = ss_gain
        self._preamp_gain = preamp_gain 

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


        # Preamp model, per-channel inversion flags, and channel labels (set by apply_preamp_config)
        self._preamp_model: str | None = None
        self._channel_invert: tuple[bool, ...] = (False, False, False, False)
        self._channel_labels: tuple[str, ...] | None = None

        # Per-channel caches used by config property getters/setters
        self._ss_config_cache = {
            0: {"Gain": None, "High-pass": None},
            1: {"Gain": None, "High-pass": None},
            2: {"Gain": None, "High-pass": None},
            3: {"Gain": None, "High-pass": None},
        }
        self._input_ground = {'A': 0, 'B': 0, 'C': 0, 'D': 0}
        self._high_pass = {0: None, 1: None, 2: None, 3: None}
        self._ttl_output_bits = 0
        self._ttl_input_bits = 0

        # set second stage gain.
        ss_gain_dict = self._fix_abcd_type(ss_gain, this_is='ss_gain')
        self._validate_ss_gain(ss_gain_dict)

        preamp_gain_dict = self._fix_abcd_type(preamp_gain, this_is='preamp_gain')
        self._validate_preamp_gain(preamp_gain_dict)
        
        # set channel modes.
        self._primary_channel_modes = primary_channel_modes
        self._secondary_channel_modes = secondary_channel_modes
        
        # function used for constructing packets from stream data.
        self._stream_packet_factory = partial(
            DataPacket8401HR, preamp_gain, ss_gain,
            self._primary_channel_modes, self._secondary_channel_modes,
            channel_invert=self._channel_invert,
        )
        
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

    @property
    def primary_channel_modes(self):
        return self._primary_channel_modes
    
    @property
    def secondary_channel_modes(self):
        return self._secondary_channel_modes

    @property
    def ss_gain(self):
        return self._ss_gain
        
    @property
    def preamp_gain(self):
        """Preamp connected to device."""
        return self._preamp_gain

    # ------------ HIGHPASS PROPERTIES ------------ 

    def get_preamp_highpass(self, channel: int) -> int:
        """Get the highpass filter value for *channel* (0-3)."""
        props = [self.preamp_highpass_0, self.preamp_highpass_1,
                 self.preamp_highpass_2, self.preamp_highpass_3]
        if 0 <= channel <= 3:
            return props[channel]
        raise ValueError(f"Invalid channel {channel}")

    @property
    def preamp_highpass_0(self) -> int:
        """Highpass filter for channel 0. 0=0.5Hz, 1=1Hz, 2=10Hz, 3=DC."""
        raw = self.write_read("GET HIGHPASS", (0,))
        self._high_pass[0] = raw.payload[0]
        return self._high_pass[0]

    @preamp_highpass_0.setter
    def preamp_highpass_0(self, value: int) -> None:
        try:
            self.write_read("SET HIGHPASS", (0, value), timeout_sec=2.0)
            self._high_pass[0] = value
        except Exception as e:
            print(f"[HIGHPASS] Failed to set preamp_highpass_0 to {value}: {e}")

    @property
    def preamp_highpass_1(self) -> int:
        """Highpass filter for channel 1."""
        raw = self.write_read("GET HIGHPASS", (1,))
        self._high_pass[1] = raw.payload[0]
        return self._high_pass[1]

    @preamp_highpass_1.setter
    def preamp_highpass_1(self, value: int) -> None:
        try:
            self.write_read("SET HIGHPASS", (1, value), timeout_sec=2.0)
            self._high_pass[1] = value
        except Exception as e:
            print(f"[HIGHPASS] Failed to set preamp_highpass_1 to {value}: {e}")

    @property
    def preamp_highpass_2(self) -> int:
        """Highpass filter for channel 2."""
        raw = self.write_read("GET HIGHPASS", (2,))
        self._high_pass[2] = raw.payload[0]
        return self._high_pass[2]

    @preamp_highpass_2.setter
    def preamp_highpass_2(self, value: int) -> None:
        try:
            self.write_read("SET HIGHPASS", (2, value), timeout_sec=2.0)
            self._high_pass[2] = value
        except Exception as e:
            print(f"[HIGHPASS] Failed to set preamp_highpass_2 to {value}: {e}")

    @property
    def preamp_highpass_3(self) -> int:
        """Highpass filter for channel 3."""
        raw = self.write_read("GET HIGHPASS", (3,))
        self._high_pass[3] = raw.payload[0]
        return self._high_pass[3]

    @preamp_highpass_3.setter
    def preamp_highpass_3(self, value: int) -> None:
        try:
            self.write_read("SET HIGHPASS", (3, value), timeout_sec=2.0)
            self._high_pass[3] = value
        except Exception as e:
            print(f"[HIGHPASS] Failed to set preamp_highpass_3 to {value}: {e}")

    # ------------ LOWPASS PROPERTIES ------------ 

    @property
    def lowpass_ch0(self) -> int:
        """Lowpass filter for channel 0 in Hz."""
        return self.write_read("GET LOWPASS", (0,)).payload[0]

    @lowpass_ch0.setter
    def lowpass_ch0(self, value: int) -> None:
        # Synchronous write so the command is fully processed before
        # subsequent operations (important for serial / /dev/ttyUSB0).
        try:
            self.write_read("SET LOWPASS", (0, value), timeout_sec=2.0)
        except Exception as e:
            print(f"[LOWPASS] Failed to set lowpass_ch0 to {value}: {e}")

    @property
    def lowpass_ch1(self) -> int:
        """Lowpass filter for channel 1 in Hz."""
        return self.write_read("GET LOWPASS", (1,)).payload[0]

    @lowpass_ch1.setter
    def lowpass_ch1(self, value: int) -> None:
        try:
            self.write_read("SET LOWPASS", (1, value), timeout_sec=2.0)
        except Exception as e:
            print(f"[LOWPASS] Failed to set lowpass_ch1 to {value}: {e}")

    @property
    def lowpass_ch2(self) -> int:
        """Lowpass filter for channel 2 in Hz."""
        return self.write_read("GET LOWPASS", (2,)).payload[0]

    @lowpass_ch2.setter
    def lowpass_ch2(self, value: int) -> None:
        try:
            self.write_read("SET LOWPASS", (2, value), timeout_sec=2.0)
        except Exception as e:
            print(f"[LOWPASS] Failed to set lowpass_ch2 to {value}: {e}")

    @property
    def lowpass_ch3(self) -> int:
        """Lowpass filter for channel 3 in Hz."""
        return self.write_read("GET LOWPASS", (3,)).payload[0]

    @lowpass_ch3.setter
    def lowpass_ch3(self, value: int) -> None:
        try:
            self.write_read("SET LOWPASS", (3, value), timeout_sec=2.0)
        except Exception as e:
            print(f"[LOWPASS] Failed to set lowpass_ch3 to {value}: {e}")

    # ------------ DC MODE PROPERTIES ------------ 

    @property
    def dc_mode_0(self) -> int:
        """DC mode for channel 0. 0=Subtract VBias, 1=Subtract AGND."""
        return self.write_read("GET DC MODE", (0,)).payload[0]

    @dc_mode_0.setter
    def dc_mode_0(self, mode: int) -> None:
        try:
            self.write_read("SET DC MODE", (0, mode), timeout_sec=2.0)
        except Exception as e:
            print(f"[DCMODE] Failed to set dc_mode_0 to {mode}: {e}")

    @property
    def dc_mode_1(self) -> int:
        """DC mode for channel 1."""
        return self.write_read("GET DC MODE", (1,)).payload[0]

    @dc_mode_1.setter
    def dc_mode_1(self, mode: int) -> None:
        try:
            self.write_read("SET DC MODE", (1, mode), timeout_sec=2.0)
        except Exception as e:
            print(f"[DCMODE] Failed to set dc_mode_1 to {mode}: {e}")

    @property
    def dc_mode_2(self) -> int:
        """DC mode for channel 2."""
        return self.write_read("GET DC MODE", (2,)).payload[0]

    @dc_mode_2.setter
    def dc_mode_2(self, mode: int) -> None:
        try:
            self.write_read("SET DC MODE", (2, mode), timeout_sec=2.0)
        except Exception as e:
            print(f"[DCMODE] Failed to set dc_mode_2 to {mode}: {e}")

    @property
    def dc_mode_3(self) -> int:
        """DC mode for channel 3."""
        return self.write_read("GET DC MODE", (3,)).payload[0]

    @dc_mode_3.setter
    def dc_mode_3(self, mode: int) -> None:
        try:
            self.write_read("SET DC MODE", (3, mode), timeout_sec=2.0)
        except Exception as e:
            print(f"[DCMODE] Failed to set dc_mode_3 to {mode}: {e}")

    # ------------ BIAS PROPERTIES ------------ 

    @property
    def bias_0(self) -> float:
        """Bias voltage on channel 0 (derived from 16-bit DAC)."""
        raw_dac = self.write_read("GET BIAS", (0,)).payload[0]
        return self.calculate_bias_dac_get_vout(raw_dac)

    @bias_0.setter
    def bias_0(self, vout: float):
        if not (-2.048 <= vout <= 2.048):
            raise ValueError("Bias voltage must be between -2.048V and 2.048V.")
        try:
            self.write_read("SET BIAS", (0, self.calculate_bias_dac_get_dac_value(vout)), timeout_sec=2.0)
        except Exception as e:
            print(f"[BIAS] Failed to set bias_0 to {vout}: {e}")

    @property
    def bias_1(self) -> float:
        """Bias voltage on channel 1."""
        raw_dac = self.write_read("GET BIAS", (1,)).payload[0]
        return self.calculate_bias_dac_get_vout(raw_dac)

    @bias_1.setter
    def bias_1(self, vout: float):
        if not (-2.048 <= vout <= 2.048):
            raise ValueError("Bias voltage must be between -2.048V and 2.048V.")
        try:
            self.write_read("SET BIAS", (1, self.calculate_bias_dac_get_dac_value(vout)), timeout_sec=2.0)
        except Exception as e:
            print(f"[BIAS] Failed to set bias_1 to {vout}: {e}")

    @property
    def bias_2(self) -> float:
        """Bias voltage on channel 2."""
        raw_dac = self.write_read("GET BIAS", (2,)).payload[0]
        return self.calculate_bias_dac_get_vout(raw_dac)

    @bias_2.setter
    def bias_2(self, vout: float):
        if not (-2.048 <= vout <= 2.048):
            raise ValueError("Bias voltage must be between -2.048V and 2.048V.")
        try:
            self.write_read("SET BIAS", (2, self.calculate_bias_dac_get_dac_value(vout)), timeout_sec=2.0)
        except Exception as e:
            print(f"[BIAS] Failed to set bias_2 to {vout}: {e}")

    @property
    def bias_3(self) -> float:
        """Bias voltage on channel 3."""
        raw_dac = self.write_read("GET BIAS", (3,)).payload[0]
        return self.calculate_bias_dac_get_vout(raw_dac)

    @bias_3.setter
    def bias_3(self, vout: float):
        if not (-2.048 <= vout <= 2.048):
            raise ValueError("Bias voltage must be between -2.048V and 2.048V.")
        try:
            self.write_read("SET BIAS", (3, self.calculate_bias_dac_get_dac_value(vout)), timeout_sec=2.0)
        except Exception as e:
            print(f"[BIAS] Failed to set bias_3 to {vout}: {e}")

    # ------------ EXT PROPERTIES ------------ 

    @property
    def ext0(self) -> int:
        """Analog value on EXT0 pin (unsigned 12-bit, 3.3V range)."""
        return self.write_read("GET EXT0 VALUE").payload[0]

    @ext0.setter
    def ext0(self, value: int) -> None:
        self.write_packet("SET EXT0", (value,))

    @property
    def ext1(self) -> int:
        """Analog value on EXT1 pin (unsigned 12-bit, 3.3V range)."""
        return self.write_read("GET EXT1 VALUE").payload[0]

    @ext1.setter
    def ext1(self, value: int) -> None:
        self.write_packet("SET EXT1", (value,))

    # ------------ INPUT GROUND PROPERTIES ------------ 

    @property
    def input_ground0(self) -> int:
        """Channel A ground state: 1=preamp, 0=grounded."""
        return self._input_ground['A']

    @input_ground0.setter
    def input_ground0(self, state: int):
        self._set_input_ground_channel('A', state)

    @property
    def input_ground1(self) -> int:
        """Channel B ground state: 1=preamp, 0=grounded."""
        return self._input_ground['B']

    @input_ground1.setter
    def input_ground1(self, state: int):
        self._set_input_ground_channel('B', state)

    @property
    def input_ground2(self) -> int:
        """Channel C ground state: 1=preamp, 0=grounded."""
        return self._input_ground['C']

    @input_ground2.setter
    def input_ground2(self, state: int):
        self._set_input_ground_channel('C', state)

    @property
    def input_ground3(self) -> int:
        """Channel D ground state: 1=preamp, 0=grounded."""
        return self._input_ground['D']

    @input_ground3.setter
    def input_ground3(self, state: int):
        self._set_input_ground_channel('D', state)

    @property
    def input_ground_all(self) -> dict[str, int]:
        """All input ground states (channels A-D) read from device."""
        payload = self.write_read("GET INPUT GROUND").payload
        self._input_ground = self.decode_channel_bitmask(payload)
        return self._input_ground

    def _set_input_ground_channel(self, channel: str, state: int):
        """Update one channel's ground state and send the full bitmask."""
        if channel not in ('A', 'B', 'C', 'D'):
            raise ValueError("Channel must be one of 'A', 'B', 'C', 'D'")
        if state not in (0, 1):
            raise ValueError("State must be 0 (grounded) or 1 (preamp)")
        self._input_ground[channel] = state
        bitmask = self.get_channel_bitmask(
            self._input_ground['A'], self._input_ground['B'],
            self._input_ground['C'], self._input_ground['D'],
        )
        self.write_packet("SET INPUT GROUND", (bitmask,))

    # ------------ TTL CONFIG PROPERTIES ------------ 

    @property
    def ttl_config(self) -> dict[str, dict[str, int]]:
        """TTL configuration with 'output' and 'input' sub-dicts."""
        response = self.write_read("GET TTL CONFIG")
        out_cfg, in_cfg = response.payload[0], response.payload[1]
        return {
            "output": self.decode_ttl_byte(bytes([out_cfg])),
            "input": self.decode_ttl_byte(bytes([in_cfg])),
        }

    @ttl_config.setter
    def ttl_config(self, config: dict[str, dict[str, int]]):
        out_bits = self.get_ttl_bitmask(**{k.lower(): v for k, v in config["output"].items()})
        in_bits = self.get_ttl_bitmask(**{k.lower(): v for k, v in config["input"].items()})
        self.write_packet("SET TTL CONFIG", (out_bits, in_bits))

    def set_ttl_outputs(self, pins: dict[str, int]):
        """Set specific TTL output states.

        :param pins: Keys from EXT0, EXT1, TTL1-TTL4; values 0 (low) or 1 (high).
        """
        modify = self.get_ttl_bitmask(**{k: 1 for k in pins})
        state = self.get_ttl_bitmask(**pins)
        self.write_packet("SET TTL OUTS", (modify, state))

    # ------------ SS CONFIG PROPERTIES ------------ 

    def get_second_stage_gain(self, channel: int) -> int:
        """Get second-stage gain for *channel* (0-3)."""
        props = [self.ss_gain_0, self.ss_gain_1, self.ss_gain_2, self.ss_gain_3]
        if 0 <= channel <= 3:
            return props[channel]
        raise ValueError(f"Invalid channel {channel}")

    def set_ss_config(self, channel: int, config: dict[str, Union[int, float]]):
        """Set the second-stage config for *channel* (0-3).

        :param channel: Channel index.
        :param config: Dict with keys ``"Gain"`` and ``"High-pass"``.
        """
        gain = config["Gain"]
        highpass = config["High-pass"]
        mask = self.get_ss_config_bitmask(gain, highpass)
        self.write_packet("SET SS CONFIG", (channel, mask))
        self._ss_config_cache[channel] = config

    @property
    def ss_config_0(self) -> dict[str, Union[float, int]]:
        """Second-stage config for channel 0 (Gain + High-pass)."""
        raw = self.write_read("GET SS CONFIG", (0,))
        return self.decode_ss_config_bitmask(raw.payload[0])

    @ss_config_0.setter
    def ss_config_0(self, config: dict[str, Union[float, int]]):
        self.set_ss_config(0, config)

    @property
    def ss_gain_0(self) -> int:
        """Second-stage gain for channel 0."""
        return self.ss_config_0["Gain"]

    @ss_gain_0.setter
    def ss_gain_0(self, gain: int):
        config = self.ss_config_0
        config["Gain"] = gain
        self.ss_config_0 = config

    @property
    def ss_config_1(self) -> dict[str, Union[float, int]]:
        """Second-stage config for channel 1."""
        raw = self.write_read("GET SS CONFIG", (1,))
        return self.decode_ss_config_bitmask(raw.payload[0])

    @ss_config_1.setter
    def ss_config_1(self, config: dict[str, Union[float, int]]):
        self.set_ss_config(1, config)

    @property
    def ss_gain_1(self) -> int:
        """Second-stage gain for channel 1."""
        return self.ss_config_1["Gain"]

    @ss_gain_1.setter
    def ss_gain_1(self, gain: int):
        config = self.ss_config_1
        config["Gain"] = gain
        self.ss_config_1 = config

    @property
    def ss_config_2(self) -> dict[str, Union[float, int]]:
        """Second-stage config for channel 2."""
        raw = self.write_read("GET SS CONFIG", (2,))
        return self.decode_ss_config_bitmask(raw.payload[0])

    @ss_config_2.setter
    def ss_config_2(self, config: dict[str, Union[float, int]]):
        self.set_ss_config(2, config)

    @property
    def ss_gain_2(self) -> int:
        """Second-stage gain for channel 2."""
        return self.ss_config_2["Gain"]

    @ss_gain_2.setter
    def ss_gain_2(self, gain: int):
        config = self.ss_config_2
        config["Gain"] = gain
        self.ss_config_2 = config

    @property
    def ss_config_3(self) -> dict[str, Union[float, int]]:
        """Second-stage config for channel 3."""
        raw = self.write_read("GET SS CONFIG", (3,))
        return self.decode_ss_config_bitmask(raw.payload[0])

    @ss_config_3.setter
    def ss_config_3(self, config: dict[str, Union[float, int]]):
        self.set_ss_config(3, config)

    @property
    def ss_gain_3(self) -> int:
        """Second-stage gain for channel 3."""
        return self.ss_config_3["Gain"]

    @ss_gain_3.setter
    def ss_gain_3(self, gain: int):
        config = self.ss_config_3
        config["Gain"] = gain
        self.ss_config_3 = config

    # ------------ MUX MODE ------------ 

    @property
    def mux_mode(self) -> int:
        """Mux mode state. 0=off, 1=on (toggles EXT1 for 2BIO/3EEG preamps)."""
        return self.write_read("GET MUX MODE").payload[0]

    @mux_mode.setter
    def mux_mode(self, mode: int | dict) -> None:
        if isinstance(mode, dict):
            mode = mode.get("mux_mode")
        self.write_packet("SET MUX MODE", (mode,))

    # ------------ TTL ANALOG PROPERTIES (read-only) ------------ 

    @property
    def ttl_analog_ext0(self) -> int:
        """Analog reading on TTL EXT0 (10-bit)."""
        return self.write_read("GET TTL ANALOG", (0,)).payload[0]

    @property
    def ttl_analog_ext1(self) -> int:
        """Analog reading on TTL EXT1."""
        return self.write_read("GET TTL ANALOG", (1,)).payload[0]

    @property
    def ttl_analog_ttl4(self) -> int:
        """Analog reading on TTL4."""
        return self.write_read("GET TTL ANALOG", (2,)).payload[0]

    @property
    def ttl_analog_ttl3(self) -> int:
        """Analog reading on TTL3."""
        return self.write_read("GET TTL ANALOG", (3,)).payload[0]

    @property
    def ttl_analog_ttl2(self) -> int:
        """Analog reading on TTL2."""
        return self.write_read("GET TTL ANALOG", (4,)).payload[0]

    @property
    def ttl_analog_ttl1(self) -> int:
        """Analog reading on TTL1."""
        return self.write_read("GET TTL ANALOG", (5,)).payload[0]

    def get_channel_preamp_gain(self, channel: int) -> float:
        """Return the preamplifier gain for *channel* (0-3)."""
        if not 0 <= channel < 4:
            raise ValueError(f"Channel index {channel} is out of range [0-3].")
        return self._preamp_gain[channel]

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
    def decode_ttl_byte(ttl_byte: bytes) -> dict[str, int]:
        """Converts the TTL bytes argument into a dictionary of integer TTL values.

        Handles both raw bytes (length 1, decoded by bit-shift) and ASCII hex
        bytes (decoded via ``conv.ascii_bytes_to_int_split``).

        :param ttl_byte: UINT8 byte containing the TTL bitmask.
        :return: Dictionary with TTL name keys and integer TTL values.
        """
        if len(ttl_byte) == 1:
            byte = ttl_byte[0]
            return {
                'EXT0': (byte >> 7) & 0x01,
                'EXT1': (byte >> 6) & 0x01,
                'TTL4': (byte >> 3) & 0x01,
                'TTL3': (byte >> 2) & 0x01,
                'TTL2': (byte >> 1) & 0x01,
                'TTL1': (byte >> 0) & 0x01,
            }
        return {
            'EXT0': conv.ascii_bytes_to_int_split(ttl_byte, 8, 7),
            'EXT1': conv.ascii_bytes_to_int_split(ttl_byte, 7, 6),
            'TTL4': conv.ascii_bytes_to_int_split(ttl_byte, 4, 3),
            'TTL3': conv.ascii_bytes_to_int_split(ttl_byte, 3, 2),
            'TTL2': conv.ascii_bytes_to_int_split(ttl_byte, 2, 1),
            'TTL1': conv.ascii_bytes_to_int_split(ttl_byte, 1, 0),
        }
    

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
    def decode_ss_config_bitmask(config: Union[bytes, bytearray, int]) -> dict[str, Union[float, int]]:
        """Converts the SS configuration byte to a dictionary with the high-pass and gain.

        :param config: UINT8 containing the SS configuration (raw bytes, bytearray, or int).
                       Bit 0: 0 = 0.5 Hz Highpass, 1 = DC Highpass.
                       Bit 1: 0 = 5x gain, 1 = 1x gain.
        """
        if isinstance(config, (bytes, bytearray)):
            value = Packet.AsciiBytesToInt(config)
        elif isinstance(config, int):
            value = config
        else:
            raise TypeError(f"Unexpected type for config: {type(config)}")

        highpass = 0.0 if (value & 0b01) else 0.5
        gain = 1 if (value & 0b10) else 5

        return {
            "High-pass": highpass,
            "Gain": gain,
        }
        

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

    # Fixed size of 8401HR binary data packet: STX(1) + cmd(4) + payload(23) + checksum(2) + ETX(1) = 31 bytes
    _STREAMING_PACKET_LEN = 31

    def read_pod_packet_streaming(self, timeout_sec: float = 0.1, validate_checksum: bool = True):
        """Read one packet (data or control) using a single read(31) when aligned. Use in streaming mode for higher throughput.

        When a fixed-size block is a complete data packet (31 bytes, ends with ETX), returns DataPacket8401HR.
        When the block starts with STX but does not end with ETX (e.g. control packet), reads to ETX, parses as
        ControlPacket, and returns it so the pipeline can deliver it to read_queue for mixed traffic.
        Raises TimeoutError if no data in timeout_sec.
        """
        if self._port is None:
            raise TypeError("PortIO object does not exist!")
        n = Pod8401HR._STREAMING_PACKET_LEN
        while True:
            data = self._port.read(n, timeout_sec)
            if data is None or len(data) < n:
                raise TimeoutError("No data received from device within timeout (streaming read)")
            if data[0:1] != PodPacket.STX:
                while True:
                    b = self._port.read(1, timeout_sec)
                    if b is None or len(b) == 0:
                        raise TimeoutError("No data received from device within timeout (streaming sync)")
                    if b == PodPacket.STX:
                        break
                rest = self._port.read(n - 1, timeout_sec)
                if rest is None or len(rest) < n - 1:
                    raise TimeoutError("No data received from device within timeout (streaming read after sync)")
                data = b + rest
            if data[-1:] != PodPacket.ETX:
                # Variable-length packet (e.g. control) - read to ETX and try to deliver as ControlPacket
                while data[-1:] != PodPacket.ETX:
                    b = self._port.read(1, timeout_sec)
                    if b is None or len(b) == 0:
                        raise TimeoutError("No data received from device within timeout (streaming read to ETX)")
                    data = data + b
                if validate_checksum and not self._validate_checksum(data):
                    continue  # discard bad packet and retry
                try:
                    return self._control_packet_factory(data)
                except Exception:
                    continue  # not a valid control packet, discard and retry
            if validate_checksum and not self._validate_checksum(data):
                raise Exception("Bad checksum for binary POD packet read (streaming).")
            return self._stream_packet_factory(data)

    def get_dict(self):
        return {
            'port': self.port,
            'preamp': self.preamp,
            'primary_channel_modes': self.primary_channel_modes,
            'secondary_channel_modes': self.secondary_channel_modes,
            'ss_gain': self.ss_gain,
            'preamp_gain': self.preamp_gain,
            'baudrate': self.baudrate,
            'device_name': self.device_name,
            'use_d2xx': self._use_d2xx,
        }

    # ------------ CONFIGURATION ------------ 

    def apply_preamp_config(self, model: str) -> None:
        """Look up *model* in the preamp registry and apply its settings.

        Sets per-channel hardware properties (dc_mode, highpass, lowpass,
        bias, ss_config), updates ``_channel_invert``, ``_preamp_gain``,
        ``_ss_gain``, and rebuilds the stream packet factory so that all
        downstream consumers see correct values.

        :param model: Preamp model number (e.g. ``"8406-SE3"``).
        :raises ValueError: If *model* is not found in the registry.
        """
        cfg = lookup_preamp_config(model)
        if cfg is None:
            from Morelia.Devices.preamp_config import list_preamp_models
            available = ", ".join(list_preamp_models())
            raise ValueError(
                f"Unknown preamp model '{model}'. "
                f"Available models: {available}"
            )

        self._preamp_model = model.strip()

        setters = [
            (self._set_dc_mode, "dc_mode"),
            (self._set_highpass, "highpass"),
            (self._set_lowpass, "lowpass"),
            (self._set_bias, "bias"),
            (self._set_ss, None),
        ]

        for ch_idx, ch_cfg in enumerate(cfg.channels):
            for setter_fn, attr_name in setters:
                try:
                    if attr_name is not None:
                        setter_fn(ch_idx, getattr(ch_cfg, attr_name))
                    else:
                        setter_fn(ch_idx, ch_cfg)
                except Exception as e:
                    print(f"[PREAMP] Failed to set channel {ch_idx}: {e}")

        invert_tuple = tuple(ch.invert for ch in cfg.channels)
        self._channel_invert = invert_tuple
        self._channel_labels = tuple(ch.label for ch in cfg.channels)

        preamp_gain_list = []
        ss_gain_list = []
        for ch_cfg in cfg.channels:
            preamp_gain_list.append(ch_cfg.preamp_gain)
            ss_gain_list.append(ch_cfg.ss_gain)
        self._preamp_gain = tuple(preamp_gain_list)
        self._ss_gain = tuple(ss_gain_list)

        self._stream_packet_factory = partial(
            DataPacket8401HR, self._preamp_gain, self._ss_gain,
            self._primary_channel_modes, self._secondary_channel_modes,
            channel_invert=self._channel_invert,
        )

        print(f"[PREAMP] Applied config '{cfg.name}' for model '{model}'")

    # -- helpers used by apply_preamp_config --------------------------------

    def _set_dc_mode(self, ch: int, value: int) -> None:
        try:
            self.write_read("SET DC MODE", (ch, value), timeout_sec=2.0)
        except Exception as e:
            print(f"[DCMODE] Failed to set channel {ch} dc_mode to {value}: {e}")

    def _set_highpass(self, ch: int, value: int) -> None:
        try:
            self.write_read("SET HIGHPASS", (ch, value), timeout_sec=2.0)
        except Exception as e:
            print(f"[HIGHPASS] Failed to set channel {ch} highpass to {value}: {e}")

    def _set_lowpass(self, ch: int, value: float) -> None:
        try:
            self.write_read("SET LOWPASS", (ch, int(value)), timeout_sec=2.0)
        except Exception as e:
            print(f"[LOWPASS] Failed to set channel {ch} lowpass to {value}: {e}")

    def _set_bias(self, ch: int, value: float) -> None:
        dac = self.calculate_bias_dac_get_dac_value(value)
        try:
            self.write_read("SET BIAS", (ch, dac), timeout_sec=2.0)
        except Exception as e:
            print(f"[BIAS] Failed to set channel {ch} bias to {value}: {e}")

    def _set_ss(self, ch: int, ch_cfg: ChannelConfig) -> None:
        config = {"Gain": ch_cfg.ss_gain, "High-pass": ch_cfg.ss_highpass}
        self.set_ss_config(ch, config)

    @property
    def preamp_model(self) -> str | None:
        """Currently configured preamp model, or ``None`` if not set via
        :meth:`apply_preamp_config`."""
        return self._preamp_model

    @preamp_model.setter
    def preamp_model(self, model: str) -> None:
        self.apply_preamp_config(model)

    @property
    def channel_invert(self) -> tuple[bool, ...]:
        """Per-channel inversion flags (True = negate stream value)."""
        return self._channel_invert

    @property
    def channel_labels(self) -> tuple[str, ...] | None:
        """Per-channel display labels from the applied preamp config,
        or ``None`` if no preamp config has been applied."""
        return self._channel_labels

    def _apply_config_recursive(self, config: dict, skip_keys: set):
        """Handle ``preamp_model`` and ``ss_config_N`` keys specially,
        then delegate to base.

        When ``preamp_model`` is present alongside other settings, the
        preamp defaults are merged with the explicit overrides **in
        memory** so that only the final values are sent to the device
        (no redundant commands).
        """
        if "preamp_model" in config:
            model = config.pop("preamp_model")
            if isinstance(model, str):
                cfg = lookup_preamp_config(model)
                if cfg is None:
                    from Morelia.Devices.preamp_config import list_preamp_models
                    raise ValueError(
                        f"Unknown preamp model '{model}'. "
                        f"Available: {', '.join(list_preamp_models())}"
                    )

                self._preamp_model = model.strip()
                self._channel_invert = tuple(ch.invert for ch in cfg.channels)
                self._channel_labels = tuple(ch.label for ch in cfg.channels)
                self._preamp_gain = tuple(ch.preamp_gain for ch in cfg.channels)
                self._ss_gain = tuple(ch.ss_gain for ch in cfg.channels)
                self._stream_packet_factory = partial(
                    DataPacket8401HR, self._preamp_gain, self._ss_gain,
                    self._primary_channel_modes, self._secondary_channel_modes,
                    channel_invert=self._channel_invert,
                )

                preamp_dict = self._preamp_config_to_dict(cfg)
                _deep_merge(preamp_dict, config)
                config.clear()
                config.update(preamp_dict)
                print(f"[PREAMP] Applied config '{cfg.name}' for model '{model}'")

        for prop, prop_value in list(config.items()):
            if prop.startswith("ss_config_") and isinstance(prop_value, dict):
                try:
                    ch = int(prop.split("_")[-1])
                    self.set_ss_config(ch, prop_value)
                except Exception as e:
                    print(f"[CONFIG] Failed to set {prop}: {e}")
                continue
        super()._apply_config_recursive(config, skip_keys)

    @staticmethod
    def _preamp_config_to_dict(cfg) -> dict:
        """Convert a :class:`PreampConfig` to a nested dict that mirrors
        the ``_property_map`` structure so it can be applied via the
        normal recursive config path."""
        result: dict = {}
        for i, ch in enumerate(cfg.channels):
            result.setdefault("highpass", {})[f"preamp_highpass_{i}"] = ch.highpass
            result.setdefault("lowpass", {})[f"lowpass_ch{i}"] = int(ch.lowpass)
            result.setdefault("dc_mode", {})[f"dc_mode_{i}"] = ch.dc_mode
            result.setdefault("bias", {})[f"bias_{i}"] = ch.bias
            result.setdefault("ss_config", {})[f"ss_config_{i}"] = {
                "Gain": ch.ss_gain,
                "High-pass": ch.ss_highpass,
            }
        return result

    _property_map: dict = {
        "preamp": {
            "preamp_model": "preamp_model",
        },
        "highpass": {
            "preamp_highpass_0": "preamp_highpass_0",
            "preamp_highpass_1": "preamp_highpass_1",
            "preamp_highpass_2": "preamp_highpass_2",
            "preamp_highpass_3": "preamp_highpass_3",
        },
        "lowpass": {
            "lowpass_ch0": "lowpass_ch0",
            "lowpass_ch1": "lowpass_ch1",
            "lowpass_ch2": "lowpass_ch2",
            "lowpass_ch3": "lowpass_ch3",
        },
        "dc_mode": {
            "dc_mode_0": "dc_mode_0",
            "dc_mode_1": "dc_mode_1",
            "dc_mode_2": "dc_mode_2",
            "dc_mode_3": "dc_mode_3",
        },
        "bias": {
            "bias_0": "bias_0",
            "bias_1": "bias_1",
            "bias_2": "bias_2",
            "bias_3": "bias_3",
        },
        "ttl_configs": {
            "ttl_config": "ttl_config",
        },
        "ext": {
            "ext0": "ext0",
            "ext1": "ext1",
        },
        "ss_config": {
            "ss_config_0": "ss_config_0",
            "ss_config_1": "ss_config_1",
            "ss_config_2": "ss_config_2",
            "ss_config_3": "ss_config_3",
        },
        "mux_mode": {
            "mux_mode": "mux_mode",
        },
        "ttl_analog": {
            "ttl_analog_ext0": "ttl_analog_ext0",
            "ttl_analog_ext1": "ttl_analog_ext1",
            "ttl_analog_ttl4": "ttl_analog_ttl4",
            "ttl_analog_ttl3": "ttl_analog_ttl3",
            "ttl_analog_ttl2": "ttl_analog_ttl2",
            "ttl_analog_ttl1": "ttl_analog_ttl1",
        },
        "input_ground": {
            "input_ground0": "input_ground0",
            "input_ground1": "input_ground1",
            "input_ground2": "input_ground2",
            "input_ground3": "input_ground3",
        },
    }
