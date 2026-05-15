import pytest
from app.protocol import bytes_to_int, int_to_bytes, int_to_bytes_signed


class TestBytesToInt:
    def test_single_byte(self):
        assert bytes_to_int(b"\x00") == 0
        assert bytes_to_int(b"\x01") == 1
        assert bytes_to_int(b"\xff") == 255

    def test_two_bytes(self):
        assert bytes_to_int(b"\x00\x00") == 0
        assert bytes_to_int(b"\x00\x01") == 1
        assert bytes_to_int(b"\x01\x00") == 256
        assert bytes_to_int(b"\xff\xff") == 65535

    def test_four_bytes(self):
        assert bytes_to_int(b"\x00\x00\x00\x00") == 0
        assert bytes_to_int(b"\x00\x00\x00\x01") == 1
        assert bytes_to_int(b"\x00\x00\x01\x00") == 256
        assert bytes_to_int(b"\x7f\xff\xff\xff") == 2147483647


class TestIntToBytes:
    def test_zero(self):
        assert int_to_bytes(0, 1) == b"\x00"
        assert int_to_bytes(0, 4) == b"\x00\x00\x00\x00"

    def test_one(self):
        assert int_to_bytes(1, 1) == b"\x01"
        assert int_to_bytes(1, 4) == b"\x00\x00\x00\x01"

    def test_256(self):
        assert int_to_bytes(256, 2) == b"\x01\x00"
        assert int_to_bytes(256, 4) == b"\x00\x00\x01\x00"

    def test_max_one_byte(self):
        assert int_to_bytes(255, 1) == b"\xff"

    def test_round_trip(self):
        for value in [0, 1, 127, 128, 255, 256, 65535, 2147483647]:
            size = 4
            assert bytes_to_int(int_to_bytes(value, size)) == value


class TestIntToBytesSigned:
    def test_positive(self):
        assert int_to_bytes_signed(1, 1) == b"\x01"
        assert int_to_bytes_signed(127, 1) == b"\x7f"

    def test_negative(self):
        assert int_to_bytes_signed(-1, 1) == b"\xff"
        assert int_to_bytes_signed(-1, 2) == b"\xff\xff"
        assert int_to_bytes_signed(-128, 1) == b"\x80"

    def test_zero(self):
        assert int_to_bytes_signed(0, 2) == b"\x00\x00"
