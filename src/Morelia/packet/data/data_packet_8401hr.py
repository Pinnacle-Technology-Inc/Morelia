from Morelia.packet.data.data_packet import DataPacket
from Morelia.packet import PrimaryChannelMode, SecondaryChannelMode
from Morelia.signal import DigitalSignal

import Morelia.packet.conversion as conv

class DataPacket8401HR(DataPacket):
    
    __slots__  = ('_ss_gain', '_preamp_gain', '_primary_channel_modes', '_secondary_channel_modes', '_ch0', '_ch1', '_ch2', '_ch3', '_ext0', '_ext1', '_ttl1', '_ttl2', '_ttl3', '_ttl4')
    def __init__(self, preamp_gain: tuple[int], ss_gain: tuple[int], 
                 primary_channel_modes: tuple[PrimaryChannelMode], secondary_channel_modes: tuple[SecondaryChannelMode],
                 raw_packet: bytes) -> None:

        super().__init__(raw_packet, 31)
            
        self._preamp_gain = preamp_gain
        self._ss_gain = ss_gain
        self._primary_channel_modes = primary_channel_modes
        self._secondary_channel_modes = secondary_channel_modes

        self._raw_packet = raw_packet

        self._ch0 = None
        self._ch1 = None
        self._ch2 = None
        self._ch3 = None
        self._ch0 = None

        self._ext0 = None
        self._ext1 = None

        self._ttl1 = None
        self._ttl2 = None
        self._ttl3 = None
        self._ttl4 = None

    @property
    def ch0(self) -> int:
        if self._ch0 is None:
            self._ch0 = DataPacket8401HR.get_primary_channel_value(self._primary_channel_modes[0], self._preamp_gain[0], self._ss_gain[0], conv.binary_bytes_to_int_split(self._raw_packet[7:16][6:9], 18, 0))

        return self._ch0

    @property
    def ch1(self) -> int:
        if self._ch1 is None:
            self._ch1 = DataPacket8401HR.get_primary_channel_value(self._primary_channel_modes[1], self._preamp_gain[1], self._ss_gain[1], conv.binary_bytes_to_int_split(self._raw_packet[7:16][4:7], 20, 2))

        return self._ch1

    @property
    def ch2(self) -> int:

        if self._ch2 is None:
            self._ch2 = DataPacket8401HR.get_primary_channel_value(self._primary_channel_modes[2], self._preamp_gain[2], self._ss_gain[2], conv.binary_bytes_to_int_split(self._raw_packet[7:16][2:5], 22, 4))

        return self._ch2

    @property
    def ch3(self) -> int:
        if self._ch3 is None:
            return DataPacket8401HR.get_primary_channel_value(self._primary_channel_modes[3], self._preamp_gain[3], self._ss_gain[3], conv.binary_bytes_to_int_split(self._raw_packet[7:16][0:3], 24, 6))

        return self._ch3

    @property
    def ext0(self) -> int | DigitalSignal:
        if self._ext0 is None:
            raw_value: int = self._raw_packet[6] & 0x80 if self._secondary_channel_modes[0] is SecondaryChannelMode.DIGITAL else conv.binary_bytes_to_int(self._raw_packet[16:18])
            self._ext0 = self.get_secondary_channel_value(self._secondary_channel_modes[0], raw_value)

        return self._ext0

    @property
    def ext1(self) -> int | DigitalSignal:
        if self._ext1 is None:
            raw_value: int = self._raw_packet[6] & 0x40 if self._secondary_channel_modes[1] is SecondaryChannelMode.DIGITAL else conv.binary_bytes_to_int(self._raw_packet[18:20])
            self._ext1 = self.get_secondary_channel_value(self._secondary_channel_modes[1], raw_value)

        return self._ext1

    @property
    def ttl1(self) -> int | DigitalSignal:

        if self._ttl1 is None:
            raw_value: int = self._raw_packet[6] & 0x01 if self._secondary_channel_modes[2]  is SecondaryChannelMode.DIGITAL else conv.binary_bytes_to_int(self._raw_packet[20:22])
            self._ttl1 = self.get_secondary_channel_value(self._secondary_channel_modes[2], raw_value)

        return self._ttl1

    @property
    def ttl2(self) -> int | DigitalSignal:

        if self._ttl2 is None:
            raw_value: int = self._raw_packet[6] & 0x02 if self._secondary_channel_modes[3] is SecondaryChannelMode.DIGITAL else conv.binary_bytes_to_int(self._raw_packet[22:24])
            self._ttl2 = self.get_secondary_channel_value(self._secondary_channel_modes[3], raw_value)

        return self._ttl2

    @property
    def ttl3(self) -> int | DigitalSignal:

        if self._ttl3 is None:
            raw_value: int = self._raw_packet[6] & 0x04 if self._secondary_channel_modes[4] is SecondaryChannelMode.DIGITAL else conv.binary_bytes_to_int(self._raw_packet[24:26])
            self._ttl3 = self.get_secondary_channel_value(self._secondary_channel_modes[4], raw_value)

        return self._ttl3

    @property
    def ttl4(self) -> int | DigitalSignal:

        if self._ttl4 is None:
            raw_value: int = self._raw_packet[6] & 0x08 if self._secondary_channel_modes[5] is SecondaryChannelMode.DIGITAL else conv.binary_bytes_to_int(self._raw_packet[26:28])
            self._ttl4 = self.get_secondary_channel_value(self._secondary_channel_modes[5], raw_value)

        return self._ttl4

    @staticmethod
    def get_primary_channel_value(channel_mode: PrimaryChannelMode, preamp_gain: int, ss_gain: int, raw_value: int) -> int:
       
        match channel_mode:
            case PrimaryChannelMode.EEG_EMG:
                voltage_at_ADC = (raw_value / 262144.0) * 4.096
                total_gain    = 10.0 * ss_gain * preamp_gain # SSGain = 1 or 5, PreampGain = 10 or 100
                real_voltage  = (voltage_at_ADC - 2.048) / total_gain # V
                return round( real_voltage * 1E6, 12)

            case PrimaryChannelMode.BIOSENSOR:
                voltage_at_ADC = (raw_value / 262144.0) * 4.096 # V
                total_gain    = 1.557 * ss_gain * 1E7 # SSGain = 1 or 5
                real_voltage  = (voltage_at_ADC - 2.048) / total_gain # V
                return round( real_voltage * 1E6, 12)

        raise ValueError('Inavlid channel mode!')
    
    @staticmethod
    def get_secondary_channel_value(channel_mode: SecondaryChannelMode, raw_value: int) -> int | DigitalSignal:
        match channel_mode:
            case SecondaryChannelMode.DIGITAL:
                return DigitalSignal.LOW if raw_value == 0 else DigitalSignal.HIGH

            case SecondaryChannelMode.ANALOG:
                return round(  ( (raw_value / 4096.0) * 3.3 ) * 1E6, 12)  # V

        raise ValueError('Inavlid channel mode!')


