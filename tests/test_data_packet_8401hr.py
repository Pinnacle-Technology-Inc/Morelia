from Morelia.packet.channel_mode import PrimaryChannelMode, SecondaryChannelMode
from Morelia.packet.data import DataPacket8401HR
import Morelia.packet.conversion as conv
from Morelia.signal import DigitalSignal

class TestDataPacket8401HR:
    def test_properties(self):
        preamp_gain = (10, 10, 10, 10)
        ss_gain = (1,1,1,1)
        
        primary_channel_modes = (
            PrimaryChannelMode.EEG_EMG,
            PrimaryChannelMode.BIOSENSOR,
            PrimaryChannelMode.BIOSENSOR,
            PrimaryChannelMode.EEG_EMG
        )
        
        secondary_channel_modes = (
            SecondaryChannelMode.DIGITAL, 
            SecondaryChannelMode.ANALOG,
            SecondaryChannelMode.DIGITAL,
            SecondaryChannelMode.DIGITAL,
            SecondaryChannelMode.ANALOG,
            SecondaryChannelMode.DIGITAL
        )

        stx: bytes = b'\x02'
        etx: bytes = b'\x03'
        command_number_bytes = conv.int_to_ascii_bytes(180, 4)
        packet_num_byte: bytes = conv.int_to_binary_bytes(245, 1)

        #\x8D <-> 10001101
        status_byte: bytes = b'\x8D'
        
        '''
        Each channel holds and 18 bit value, packed over 3 bytes.
        Channel | Decimal | Binary (18 bits, 2's complement)
        ====================================================
        3       | 25222   | 000110001010000110
        2       | 7500    | 000001110101001100
        1       | 0       | 000000000000000000
        0       | 6200    | 000001100000111000
        full channel bytes:
            00011000 10100001 10000001 11010100 11000000 00000000 00000000 00001100 000111000
            in hex: 18A1A62B4000001838
        '''
        channel_bytes: bytes = b'\x18\xA1\x81\xD4\xC0\x00\x00\x18\x38'
        ext0_analog_bytes: bytes = conv.int_to_binary_bytes(33, 2)
        ext1_analog_bytes: bytes = conv.int_to_binary_bytes(300, 2)

        ext_bytes: bytes = ext0_analog_bytes + ext1_analog_bytes

        ttl1_analog_bytes: bytes = conv.int_to_binary_bytes(22, 2)
        ttl2_analog_bytes: bytes = conv.int_to_binary_bytes(22, 2)
        ttl3_analog_bytes: bytes = conv.int_to_binary_bytes(147, 2)
        ttl4_analog_bytes: bytes = conv.int_to_binary_bytes(0, 2)
        
        ttl_bytes: bytes = ttl1_analog_bytes + ttl2_analog_bytes + ttl3_analog_bytes + ttl4_analog_bytes

        test_packet_payload = packet_num_byte + status_byte + channel_bytes + ext_bytes + ttl_bytes

        checksum: bytes = conv.int_to_ascii_bytes(sum(test_packet_payload) & 0xFF, 2)

        test_packet_bytes: bytes = stx + command_number_bytes + test_packet_payload + checksum + etx
        test_packet = DataPacket8401HR(preamp_gain, ss_gain, primary_channel_modes, secondary_channel_modes, test_packet_bytes)

        assert test_packet.ch0 == DataPacket8401HR.get_primary_channel_value(primary_channel_modes[0], preamp_gain[0], ss_gain[0], 6200)
        assert test_packet.ch1 == DataPacket8401HR.get_primary_channel_value(primary_channel_modes[1], preamp_gain[1], ss_gain[1], 0)
        assert test_packet.ch2 == DataPacket8401HR.get_primary_channel_value(primary_channel_modes[2], preamp_gain[2], ss_gain[2], 7500)
        assert test_packet.ch3 == DataPacket8401HR.get_primary_channel_value(primary_channel_modes[3], preamp_gain[3], ss_gain[3], 25222)

        assert test_packet.ext0 == DigitalSignal.HIGH
        assert test_packet.ext1 == DataPacket8401HR.get_secondary_channel_value(SecondaryChannelMode.ANALOG, 300)

        assert test_packet.ttl1 == DigitalSignal.HIGH
        assert test_packet.ttl2 == DigitalSignal.LOW
        assert test_packet.ttl3 == DataPacket8401HR.get_secondary_channel_value(SecondaryChannelMode.ANALOG, 147)
        assert test_packet.ttl4 == DigitalSignal.HIGH
