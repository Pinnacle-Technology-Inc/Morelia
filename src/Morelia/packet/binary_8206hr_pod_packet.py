from Morelia.packet import BinaryPodPacket
from Morelia.signal import TTL

import Morelia.packet.conversion as conv

from functools import cache

class Binary8206HRPodPacket(BinaryPodPacket):
    def __init__(self, raw_packet: bytes, preamp_gain: int) -> None:
        self._preamp_gain = preamp_gain
        #self._min_length = 
        super().__init__(raw_packet)
    
    @property
    @cache
    def ch0(self) -> int:
        return Binary8206HRPodPacket.to_uv(self._raw_packet[7:9], self._preamp_gain)

    @property
    @cache
    def ch1(self) -> int:
        return Binary8206HRPodPacket.to_uv(self._raw_packet[9:11], self._preamp_gain)

    @property
    @cache
    def ch2(self) -> int:
        return Binary8206HRPodPacket.to_uv(self._raw_packet[11:13], self._preamp_gain)
 
    @property
    @cache
    def ttl1(self) -> int:
        return TTL.LOW if self._raw_packet[6] & 0x80 == 0 else TTL.HIGH

    @property
    @cache
    def ttl2(self) -> int:
        return TTL.LOW if self._raw_packet[6] & 0x40 == 0 else TTL.HIGH
    @property
    @cache
    def ttl3(self) -> int:
        return TTL.LOW if self._raw_packet[6] & 0x20 == 0 else TTL.HIGH

    @property
    @cache
    def ttl4(self) -> int:
        return TTL.LOW if self._raw_packet[6] & 0x10 == 0 else TTL.HIGH

    def to_uv(raw_value: bytes, preamp_gain: int) -> float:
        # convert binary message from POD to integer
        #value_int = binary_bytes_to_int(value, byteorder=Endianness.LITTLE)
        # calculate voltage 
        value = conv.binary_bytes_to_int(raw_value, conv.Endianness.LITTLE)
        voltage_adc = ( value / 65535.0 ) * 4.096 # V
        total_gain = preamp_gain * 50.2918
        # return the real value at input to preamplifier 
        real_voltage = ( voltage_adc - 2.048 ) / total_gain
        return round(real_voltage * 1E6, 12)

    #this may not be exactly accurate cuz of rounding errors
    @staticmethod
    def uv_to_int(uv: float, preamp_gain: int) -> int:
        voltage = uv/1E6
        total_gain = preamp_gain * 50.2918
        voltage_adc = voltage*total_gain + 2.048
        return (voltage_adc // 4.096) * 65535.0 
