import pytest
from Morelia.packet import PodPacket
import Morelia.packet.conversion as conversion

class TestPodPacket:
    def test_command_number_valid(self):
        #packet: STX + 0 + 0 + 1 + 0 + ETX
        test_packet = PodPacket(b'\x02' + conversion.int_to_ascii_bytes(10, 4)  + b'\x03')
        assert test_packet.command_number == 10

    def test_no_command_number(self):
        #packet: STX + ETX
        test_packet = PodPacket(b'\x02\x03')

        with pytest.raises(AttributeError):
            test_packet.command_number

    def test_invalid_command_number(self):
        #packet: STX + 0 + 0 + I + 0 +ETX
        test_packet = PodPacket(b'\x02\x30\x30\x49\x30\x03')

        with pytest.raises(ValueError):
            test_packet.command_number

    def test_equality(self):
        test_packet1 = PodPacket(b'\x02' + conversion.int_to_ascii_bytes(24, 4)  + b'\x03')
        test_packet2 = PodPacket(b'\x02' + conversion.int_to_ascii_bytes(24, 4)  + b'\x03')
        test_packet3 = PodPacket(b'\x02' + conversion.int_to_ascii_bytes(48, 4)  + b'\x03')

        assert test_packet1 == test_packet2
        assert test_packet1 != test_packet3
        assert test_packet2 != test_packet3
