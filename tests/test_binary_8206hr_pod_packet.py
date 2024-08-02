from Morelia.packet import Binary8206HRPodPacket
import Morelia.packet.conversion as conv
from Morelia.signal import TTL

class TestBinary8206HRPodPacket:
    def test_properties(self):
        preamp_gain: int = 10
        stx: bytes = b'\x02'
        etx: bytes = b'\x03'
        command_number_bytes = conv.int_to_ascii_bytes(180, 4)

        packet_num_bytes: bytes = conv.int_to_binary_bytes(245, 1)
        
        #160 <-> 01010000

        ttl_bytes: bytes = conv.int_to_binary_bytes(160, 1) 
        ch0_bytes: bytes = conv.int_to_binary_bytes(conv.neg_int_to_twos_complement(-4,3), 2, conv.Endianness.LITTLE)
        ch1_bytes: bytes = conv.int_to_binary_bytes(200, 2, conv.Endianness.LITTLE)
        ch2_bytes: bytes = conv.int_to_binary_bytes(97, 2, conv.Endianness.LITTLE)
        ch3_bytes: bytes = conv.int_to_binary_bytes(conv.neg_int_to_twos_complement(-77, 7), 2, conv.Endianness.LITTLE)
        test_packet_payload: bytes = packet_num_bytes + ttl_bytes + ch0_bytes + ch1_bytes + ch2_bytes
        checksum: bytes = conv.int_to_ascii_bytes(sum(test_packet_payload) & 0xFF, 2)
        #checksum: bytes = Binary8206HRPodPacket.calculate_checksum(test_packet_payload)
        test_packet_bytes: bytes = stx + command_number_bytes + test_packet_payload + checksum + etx

        test_packet = Binary8206HRPodPacket(test_packet_bytes, preamp_gain)
        
        #need to run binary bytes to voltage conversion on and round channel values
        assert test_packet.ch0 == Binary8206HRPodPacket.to_uv(ch0_bytes, preamp_gain) 
        assert test_packet.ch1 == Binary8206HRPodPacket.to_uv(ch1_bytes, preamp_gain) 
        assert test_packet.ch2 == Binary8206HRPodPacket.to_uv(ch2_bytes, preamp_gain) 
        assert test_packet.ttl1 == TTL.HIGH
        assert test_packet.ttl2 == TTL.LOW
        assert test_packet.ttl3 == TTL.HIGH
        assert test_packet.ttl4 == TTL.LOW
        #test checksum in some way?
