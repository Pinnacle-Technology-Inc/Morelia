import random

from Morelia.packet.data import DataPacket8274D
from Morelia.Devices.PodDevice_8274D import Pod8274D
from tests.mocks.packet.data.MockDataPacket8274D import MockDataPacket8274D

class TestDataPacket8274D:
    def test_properties(self):
        primary_gain, secondary_gain = Pod8274D._DEVICE_GAINS["8274-SL"]

        mock_packet = MockDataPacket8274D()

        test_packet = DataPacket8274D(
            raw_packet=mock_packet.to_bytes(),
            primary_gain=primary_gain,
            secondary_gain=secondary_gain,
        )

        # Test packet object against mock packet
        for i, (ch5, ch6, ch7) in enumerate(zip(test_packet.ch5, test_packet.ch6, test_packet.ch7)):
            assert ch5 == DataPacket8274D.get_primary_channel_value(
                value=mock_packet.ch5[i],
                primary_gain=primary_gain,
                secondary_gain=secondary_gain,
            )
            assert ch6 == DataPacket8274D.get_primary_channel_value(
                value=mock_packet.ch6[i],
                primary_gain=primary_gain,
                secondary_gain=secondary_gain,
            )
            assert ch7 == DataPacket8274D.get_primary_channel_value(
                value=mock_packet.ch7[i],
                primary_gain=primary_gain,
                secondary_gain=secondary_gain,
            )
