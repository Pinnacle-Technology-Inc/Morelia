from Morelia.packet.data.data_packet import DataPacket
from Morelia.signal import DigitalSignal

import Morelia.packet.conversion as conv

class DataPacket8206HR(DataPacket):

    __slots__ = ('_ch0', '_ch1', '_ch2', '_ttl1', '_ttl2', '_ttl3', '_ttl4')
    def __init__(self, raw_packet: bytes, preamp_gain: int) -> None:
        self._preamp_gain = preamp_gain
        super().__init__(raw_packet, 16)

        self._ch0 = None
        self._ch1 = None
        self._ch2 = None

        self._ttl1 = None
        self._ttl2 = None
        self._ttl3 = None
        self._ttl4 = None
    
    @property
    def ch0(self) -> int:
        if self._ch0 is None:
            self._ch0 = DataPacket8206HR.get_primary_channel_value(self._raw_packet[7:9], self._preamp_gain)
        return self._ch0

    @property
    def ch1(self) -> int:
        if self._ch1 is None:
            self._ch1 = DataPacket8206HR.get_primary_channel_value(self._raw_packet[9:11], self._preamp_gain)
        return self._ch1

    @property
    def ch2(self) -> int:
        if self._ch2 is None:
            self._ch2 = DataPacket8206HR.get_primary_channel_value(self._raw_packet[11:13], self._preamp_gain)
        return self._ch2
 
    @property
    def ttl1(self) -> int:
        if self._ttl1 is None:
            self._ttl1 = DigitalSignal.LOW if self._raw_packet[6] & 0x80 == 0 else DigitalSignal.HIGH
        return self._ttl1

    @property
    def ttl2(self) -> int:
        if self._ttl2 is None:
            self._ttl2 = DigitalSignal.LOW if self._raw_packet[6] & 0x40 == 0 else DigitalSignal.HIGH
        return self._ttl2

    @property
    def ttl3(self) -> int:
        if self._ttl3 is None:
            self._ttl3 = DigitalSignal.LOW if self._raw_packet[6] & 0x20 == 0 else DigitalSignal.HIGH
        return self._ttl3

    @property
    def ttl4(self) -> int:
        if self._ttl4 is None:
            self._ttl4 = DigitalSignal.LOW if self._raw_packet[6] & 0x10 == 0 else DigitalSignal.HIGH
        return self._ttl4

    @staticmethod
    def get_primary_channel_value(raw_value: bytes, preamp_gain: int) -> float:
        # calculate voltage 
        value = conv.binary_bytes_to_int(raw_value, conv.Endianness.LITTLE)
        voltage_adc = ( value / 65535.0 ) * 4.096 # V
        total_gain = preamp_gain * 50.2918
        real_voltage = ( voltage_adc - 2.048 ) / total_gain
        return round(real_voltage * 1E6, 12)

