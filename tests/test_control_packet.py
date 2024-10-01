from Morelia.packet import ControlPacket
from Morelia.packet import conversion as conv
from Morelia.Commands import CommandSet

from pytest import raises
from functools import partial

class TestControlPacket:

    def test_properties_standard_payload(self):

        stx: bytes = b'\x02'
        etx: bytes = b'\x03'
        
        command_number_bytes: bytes = conv.int_to_ascii_bytes(12, 4)

        firmware_version_bytes: bytes = conv.int_to_ascii_bytes(10, 2)
        firmware_subversion_bytes: bytes = conv.int_to_ascii_bytes(4, 2)
        firmware_revision_bytes: bytes = conv.int_to_ascii_bytes(252, 4)

        firmware_bytes: bytes = firmware_version_bytes + firmware_subversion_bytes + firmware_revision_bytes
        
        test_packet_payload: bytes = command_number_bytes + firmware_bytes

        checksum: bytes = conv.int_to_ascii_bytes(sum(test_packet_payload) & 0xFF, 2)

        packet = ControlPacket(CommandSet(), stx + test_packet_payload + checksum + etx)
        
        assert packet.payload[0] == 10
        assert packet.payload[1] == 4
        assert packet.payload[2] == 252

    def test_properties_nonstandard_payload(self):

        stx: bytes = b'\x02'
        etx: bytes = b'\x03'
        
        command_number_bytes: bytes = conv.int_to_ascii_bytes(7, 4)

        value_1_bytes: bytes = conv.int_to_ascii_bytes(1010, 10)
        value_2_bytes: bytes = conv.int_to_ascii_bytes(20, 4)
        
        def decode_payload(command_number: int, payload: bytes) -> tuple[int]:
            if command_number == 7:
                return (conv.ascii_bytes_to_int(payload[0:10]), conv.ascii_bytes_to_int(payload[10::]))
            else: 
                return ControlPacket.decode_payload_from_cmd_set(command_number, payload)

        test_packet_payload: bytes = command_number_bytes + value_1_bytes + value_2_bytes

        checksum: bytes = conv.int_to_ascii_bytes(sum(test_packet_payload) & 0xFF, 2)

        packet = ControlPacket(decode_payload, stx + test_packet_payload + checksum + etx)

        assert packet.payload[0] == 1010
        assert packet.payload[1] == 20

    def test_payload_too_short(self):
        with raises(ValueError):
            packet = ControlPacket(CommandSet(), b'0x02')
            packet.payload
