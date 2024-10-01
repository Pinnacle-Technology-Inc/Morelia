import Morelia.packet.conversion as conv
import pytest

class TestConversion:
    def test_neg_int_to_twos_complement(self):

        #expecting: 252 <-> 1111 1100
        assert conv.neg_int_to_twos_complement(-4, 8) == 252

        #expecting: 129 <-> 1000 0001
        assert conv.neg_int_to_twos_complement(-127, 8) == 129

        #expecting: 255 <-> 1111 1111
        assert conv.neg_int_to_twos_complement(-1, 8) == 255

        #expecting: 249 <-> 1111 1001
        assert conv.neg_int_to_twos_complement(-7, 8) == 249

        with pytest.raises(ValueError):
            conv.neg_int_to_twos_complement(100,8)

    def test_twos_complement_to_neg_int(self):

        assert conv.twos_complement_to_neg_int(252, 8) == -4

        assert conv.twos_complement_to_neg_int(129, 8) == -127

        assert conv.twos_complement_to_neg_int(255, 8) == -1

        assert conv.twos_complement_to_neg_int(249, 8) == -7

        with pytest.raises(ValueError):
            conv.twos_complement_to_neg_int(-7,8)
            conv.twos_complement_to_neg_int(7,8)

    def test_neg_int_twos_complement_inverses(self):
        
        #check neg to 2's comp undoes twos comp to neg.
        assert conv.neg_int_to_twos_complement(conv.twos_complement_to_neg_int(252, 8),8) == 252

        #2's comp to neg undoes neg int to twos comp.
        assert conv.twos_complement_to_neg_int(conv.neg_int_to_twos_complement(-4, 8), 8) == -4

#TODO: add tests for split methods

    def test_ascii_bytes_to_int(self):
        assert conv.ascii_bytes_to_int(b'\x31\x30') == 16
        assert conv.ascii_bytes_to_int(b'\x41\x38\x30') == 2688
        assert conv.ascii_bytes_to_int(b'\x46\x43', signed=True) == -4

    def test_int_to_ascii_bytes(self):
        assert conv.int_to_ascii_bytes(16, 2) == b'\x31\x30'
        assert conv.int_to_ascii_bytes(2688, 3) == b'\x41\x38\x30'
        assert conv.int_to_ascii_bytes(-4, 2) == b'\x46\x43'
        assert conv.int_to_ascii_bytes(16, 4) == b'\x30\x30\x31\x30'
        assert conv.int_to_ascii_bytes(-4, 3) == b'\x46\x46\x43'

    def test_int_ascii_bytes_inverse(self):
        assert conv.int_to_ascii_bytes(conv.ascii_bytes_to_int(b'\x31\x30'), 2) == b'\x31\x30'
        assert conv.ascii_bytes_to_int(conv.int_to_ascii_bytes(16,2)) == 16

    def test_ascii_bytes_to_int_split(self):
        assert conv.ascii_bytes_to_int_split(b'\x41\x38\x30', 11, 8) == 2

    def test_binary_bytes_to_int(self):
       assert conv.binary_bytes_to_int(b'ab') == 24930 
       assert conv.binary_bytes_to_int(b'ab', byteorder=conv.Endianness.LITTLE) == 25185
       assert conv.binary_bytes_to_int(b'\xFF', signed=True) == -1

    def test_int_to_binary_bytes(self):
        assert conv.int_to_binary_bytes(24930, 2) == b'ab'
        assert conv.int_to_binary_bytes(24930, 2, conv.Endianness.LITTLE) == b'ba'

        with pytest.raises(OverflowError):
            conv.int_to_binary_bytes(24930, 1)


    def test_int_binary_bytes_inverse(self):
        assert conv.int_to_binary_bytes(conv.binary_bytes_to_int(b'ab'), 2) == b'ab'
        assert conv.binary_bytes_to_int(conv.int_to_binary_bytes(24930, 2)) == 24930
    
    def test_binary_bytes_to_int_split(self):
       assert conv.binary_bytes_to_int_split(b'ab', 12, 5) == 11

    def test_ascii_bytes_to_binary_bytes(self):
        assert conv.ascii_bytes_to_binary_bytes(b'\x31\x30', 1) == b'\x10'
        assert conv.ascii_bytes_to_binary_bytes(b'\x31\x30', 4) == b'\x00\x00\x00\x10'
        assert conv.ascii_bytes_to_binary_bytes(b'\x36\x38\x31\x30', 2, conv.Endianness.LITTLE) == b'\x10\x68'

        with pytest.raises(OverflowError):
            assert conv.ascii_bytes_to_binary_bytes(b'\x36\x38\x31\x30', 1)

    def test_binary_bytes_to_ascii_bytes(self):
        assert conv.binary_bytes_to_ascii_bytes(b'\x10', 2) == b'\x31\x30'
        assert conv.binary_bytes_to_ascii_bytes(b'\x00\x00\x00\x10', 2) == b'\x31\x30'
        assert conv.binary_bytes_to_ascii_bytes(b'\x10\x68', 4, conv.Endianness.LITTLE) == b'\x36\x38\x31\x30'

    def test_ascii_bytes_binary_bytes_inverse(self):
        assert conv.ascii_bytes_to_binary_bytes(conv.binary_bytes_to_ascii_bytes(b'\x10', 2), 1) == b'\x10'
        assert conv.binary_bytes_to_ascii_bytes(conv.ascii_bytes_to_binary_bytes(b'\x31\x30', 1), 2) == b'\x31\x30'
