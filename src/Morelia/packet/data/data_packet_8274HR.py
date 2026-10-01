from Morelia.packet.data.data_packet import DataPacket


class DataPacket8274HR(DataPacket):
    """Decode the signed 14-bit EEG words used by 8274HR/M2 and 8474HR/M2."""

    def __init__(self, raw_packet: bytes, number_channels: int = 3,
                 primary_gain: float = 100, secondary_gain: float = 26) -> None:
        if number_channels not in (3, 4):
            raise ValueError("number_channels must be 3 or 4")
        super().__init__(raw_packet=raw_packet, min_length=259)
        self._channels = [[] for _ in range(number_channels)]
        self._raw_channels = [[] for _ in range(number_channels)]
        self._number_channels = number_channels
        for i in range(16, 256, 2):
            word = int.from_bytes(raw_packet[i:i + 2], "little")
            channel = word >> 14
            if channel >= number_channels:
                raise ValueError(f"Invalid HR channel ID: {channel}")
            adc = word & 0x3fff
            if adc & 0x2000:
                adc -= 0x4000
            self._raw_channels[channel].append(adc)
            # Signed 14-bit ADC spans -1.21 V to +1.21 V.
            microvolts = adc * (2.42 / 16384) * 1e6 / (primary_gain * secondary_gain)
            if channel == 2 and number_channels == 3:
                microvolts = -microvolts
            self._channels[channel].append(round(microvolts, 12))

    @property
    def packet_counter(self) -> int:
        return int.from_bytes(self._raw_packet[12:14], "little")

    @property
    def channels(self) -> list[list[float]]:
        return self._channels

    @property
    def raw_channels(self) -> list[list[int]]:
        """Signed ADC counts for device-specific channel conversion."""
        return self._raw_channels

    @property
    def ch1(self) -> list[float]:
        return self._channels[0]

    @property
    def ch2(self) -> list[float]:
        return self._channels[1]

    @property
    def ch3(self) -> list[float]:
        return self._channels[2]

    @property
    def ch4(self) -> list[float]:
        return self._channels[3] if self._number_channels == 4 else []
