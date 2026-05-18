from tests.conftest import make_buffer
from app.tools import (
    encode_uvarint,
    read_uvarint,
    read_compact_string,
    read_compact_nullable_string,
)


class TestUvarint:
    def test_encode_zero(self):
        assert encode_uvarint(0) == b"\x00"

    def test_encode_one(self):
        assert encode_uvarint(1) == b"\x01"

    def test_encode_127(self):
        assert encode_uvarint(127) == b"\x7f"

    def test_encode_128(self):
        # 128 needs two bytes: 0x80 | 0 = 0x80, then 0x01
        assert encode_uvarint(128) == b"\x80\x01"

    def test_encode_16383(self):
        assert encode_uvarint(16383) == b"\xff\x7f"

    def test_encode_16384(self):
        assert encode_uvarint(16384) == b"\x80\x80\x01"

    def test_round_trip(self):
        for value in [0, 1, 63, 64, 127, 128, 300, 16383, 16384, 100000]:
            buf = make_buffer(encode_uvarint(value))
            assert read_uvarint(buf) == value

    def test_read_single_byte(self):
        buf = make_buffer(b"\x05")
        assert read_uvarint(buf) == 5

    def test_read_multi_byte(self):
        buf = make_buffer(b"\x80\x01")
        assert read_uvarint(buf) == 128

    def test_read_advances_position(self):
        buf = make_buffer(b"\x80\x01\xff")
        read_uvarint(buf)
        assert buf.position == 2


class TestReadCompactString:
    def test_non_empty_string(self):
        # compact string: length byte = len(data) + 1
        data = b"hello"
        raw = bytes([len(data) + 1]) + data
        buf = make_buffer(raw)
        assert read_compact_string(buf) == data

    def test_empty_string(self):
        # length byte = 1 means 0 bytes follow
        buf = make_buffer(b"\x01")
        assert read_compact_string(buf) == b""

    def test_advances_position(self):
        data = b"abc"
        raw = bytes([len(data) + 1]) + data + b"\xff"
        buf = make_buffer(raw)
        read_compact_string(buf)
        assert buf.position == 1 + len(data)


class TestReadCompactNullableString:
    def test_null_string(self):
        # length byte = 0 means null
        buf = make_buffer(b"\x00")
        assert read_compact_nullable_string(buf) is None

    def test_empty_string(self):
        # length byte = 1 means 0 bytes → empty string
        buf = make_buffer(b"\x01")
        assert read_compact_nullable_string(buf) == b""

    def test_non_empty_string(self):
        data = b"kafka"
        raw = bytes([len(data) + 1]) + data
        buf = make_buffer(raw)
        assert read_compact_nullable_string(buf) == data

    def test_advances_position(self):
        data = b"ab"
        raw = bytes([len(data) + 1]) + data + b"\xee"
        buf = make_buffer(raw)
        read_compact_nullable_string(buf)
        assert buf.position == 1 + len(data)
