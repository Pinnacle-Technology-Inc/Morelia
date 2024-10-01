from Morelia.packet.data import DataPacket8206HR
import Morelia.packet.conversion as conv
from Morelia.signal import DigitalSignal

class TestDataPacket8206HR:
    def test_properties(self):
        preamp_gain: int = 10
        stx: bytes = b'\x02'
        etx: bytes = b'\x03'
        command_number_bytes = conv.int_to_ascii_bytes(180, 4)
        packet_num_bytes: bytes = conv.int_to_binary_bytes(245, 1)
        
        #160 <-> 01010000

        ttl_bytes: bytes = conv.int_to_binary_bytes(160, 1) 
        ch0_bytes: bytes = conv.int_to_binary_bytes(4, 2, conv.Endianness.LITTLE)
        ch1_bytes: bytes = conv.int_to_binary_bytes(200, 2, conv.Endianness.LITTLE)
        ch2_bytes: bytes = conv.int_to_binary_bytes(97, 2, conv.Endianness.LITTLE)
        ch3_bytes: bytes = conv.int_to_binary_bytes(77, 2, conv.Endianness.LITTLE)
        test_packet_payload: bytes = command_number_bytes + packet_num_bytes + ttl_bytes + ch0_bytes + ch1_bytes + ch2_bytes
        checksum: bytes = conv.int_to_ascii_bytes(sum(test_packet_payload) & 0xFF, 2)
        #checksum: bytes = DataPacket8206HR.calculate_checksum(test_packet_payload)
        test_packet_bytes: bytes = stx + test_packet_payload + checksum + etx

        test_packet = DataPacket8206HR(test_packet_bytes, preamp_gain)
        
        assert test_packet.ch0 == DataPacket8206HR.get_primary_channel_value(ch0_bytes, preamp_gain) 
        assert test_packet.ch1 == DataPacket8206HR.get_primary_channel_value(ch1_bytes, preamp_gain) 
        assert test_packet.ch2 == DataPacket8206HR.get_primary_channel_value(ch2_bytes, preamp_gain) 
        assert test_packet.ttl1 == DigitalSignal.HIGH
        assert test_packet.ttl2 == DigitalSignal.LOW
        assert test_packet.ttl3 == DigitalSignal.HIGH
        assert test_packet.ttl4 == DigitalSignal.LOW
        #test checksum in some way?
