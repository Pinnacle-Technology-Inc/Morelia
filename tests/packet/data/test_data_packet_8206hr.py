import Morelia.packet.conversion as conv

from Morelia.packet.data import DataPacket8206HR
from Morelia.signal import DigitalSignal

from tests.mocks.packet.data.MockDataPacket8206HR import MockDataPacket8206HR

class TestDataPacket8206HR:
    def test_properties(self):
        preamp_gain = 10

        mock_packet = MockDataPacket8206HR(
            ch0=4,
            ch1=200,
            ch2=97,
            ttl1=1,
            ttl2=0,
            ttl3=1,
            ttl4=0,
            packet_number=245,
        )

        test_packet = DataPacket8206HR(
            raw_packet=mock_packet.to_bytes(),
            preamp_gain=preamp_gain,
        )

        # Test packet object against mock packet
        assert test_packet.ch0 == DataPacket8206HR.get_primary_channel_value(
            conv.int_to_binary_bytes(mock_packet.ch0, 2, conv.Endianness.LITTLE),
            preamp_gain,
        )

        assert test_packet.ch1 == DataPacket8206HR.get_primary_channel_value(
            conv.int_to_binary_bytes(mock_packet.ch1, 2, conv.Endianness.LITTLE),
            preamp_gain,
        )

        assert test_packet.ch2 == DataPacket8206HR.get_primary_channel_value(
            conv.int_to_binary_bytes(mock_packet.ch2, 2, conv.Endianness.LITTLE),
            preamp_gain,
        )

        assert test_packet.ttl1 == (
            DigitalSignal.HIGH if mock_packet.ttl1 else DigitalSignal.LOW
        )
        assert test_packet.ttl2 == (
            DigitalSignal.HIGH if mock_packet.ttl2 else DigitalSignal.LOW
        )
        assert test_packet.ttl3 == (
            DigitalSignal.HIGH if mock_packet.ttl3 else DigitalSignal.LOW
        )
        assert test_packet.ttl4 == (
            DigitalSignal.HIGH if mock_packet.ttl4 else DigitalSignal.LOW
        )