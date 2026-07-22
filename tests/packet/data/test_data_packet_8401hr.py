from Morelia.packet.channel_mode import PrimaryChannelMode, SecondaryChannelMode
from Morelia.packet.data import DataPacket8401HR
from Morelia.signal import DigitalSignal

from tests.mocks.packet.data.MockDataPacket8401HR import MockDataPacket8401HR


class TestDataPacket8401HR:
    def test_properties(self):
        preamp_gain = (10, 10, 10, 10)
        ss_gain = (1, 1, 1, 1)

        primary_channel_modes = (
            PrimaryChannelMode.EEG_EMG,
            PrimaryChannelMode.BIOSENSOR,
            PrimaryChannelMode.BIOSENSOR,
            PrimaryChannelMode.EEG_EMG,
        )

        secondary_channel_modes = (
            SecondaryChannelMode.DIGITAL,
            SecondaryChannelMode.ANALOG,
            SecondaryChannelMode.DIGITAL,
            SecondaryChannelMode.DIGITAL,
            SecondaryChannelMode.ANALOG,
            SecondaryChannelMode.DIGITAL,
        )

        mock_packet = MockDataPacket8401HR(
            ch0=6200,
            ch1=0,
            ch2=7500,
            ch3=25222,
            ext0=33,
            ext1=300,
            ttl1=22,
            ttl2=22,
            ttl3=147,
            ttl4=0,
            packet_number=245,
            status=0x8D,
        )

        test_packet = DataPacket8401HR(
            preamp_gain,
            ss_gain,
            primary_channel_modes,
            secondary_channel_modes,
            mock_packet.to_bytes(),
        )

        # Primary channels
        assert test_packet.ch0 == DataPacket8401HR.get_primary_channel_value(
            primary_channel_modes[0],
            preamp_gain[0],
            ss_gain[0],
            mock_packet.ch0,
        )
        assert test_packet.ch1 == DataPacket8401HR.get_primary_channel_value(
            primary_channel_modes[1],
            preamp_gain[1],
            ss_gain[1],
            mock_packet.ch1,
        )
        assert test_packet.ch2 == DataPacket8401HR.get_primary_channel_value(
            primary_channel_modes[2],
            preamp_gain[2],
            ss_gain[2],
            mock_packet.ch2,
        )
        assert test_packet.ch3 == DataPacket8401HR.get_primary_channel_value(
            primary_channel_modes[3],
            preamp_gain[3],
            ss_gain[3],
            mock_packet.ch3,
        )

        # Secondary channels
        assert test_packet.ext0 == DigitalSignal.HIGH
        assert test_packet.ext1 == DataPacket8401HR.get_secondary_channel_value(
            secondary_channel_modes[1],
            mock_packet.ext1,
        )

        assert test_packet.ttl1 == DigitalSignal.HIGH
        assert test_packet.ttl2 == DigitalSignal.LOW
        assert test_packet.ttl3 == DataPacket8401HR.get_secondary_channel_value(
            secondary_channel_modes[4],
            mock_packet.ttl3,
        )
        assert test_packet.ttl4 == DigitalSignal.HIGH