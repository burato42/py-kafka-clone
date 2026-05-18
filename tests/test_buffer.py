from tests.conftest import make_buffer


class TestBufferReadBytes:
    def test_reads_correct_slice(self):
        buf = make_buffer(b"\x01\x02\x03\x04")
        assert buf.read_bytes(2) == b"\x01\x02"

    def test_advances_position(self):
        buf = make_buffer(b"\x01\x02\x03\x04")
        buf.read_bytes(2)
        assert buf.read_bytes(2) == b"\x03\x04"

    def test_read_single_byte(self):
        buf = make_buffer(b"\xab")
        assert buf.read_bytes(1) == b"\xab"

    def test_read_zero_bytes(self):
        buf = make_buffer(b"\x01\x02")
        assert buf.read_bytes(0) == b""
        assert buf.position == 0


class TestBufferPeekBytes:
    def test_does_not_advance_position(self):
        buf = make_buffer(b"\x01\x02\x03")
        buf.peek_bytes(2)
        assert buf.position == 0

    def test_returns_correct_slice(self):
        buf = make_buffer(b"\x01\x02\x03")
        assert buf.peek_bytes(2) == b"\x01\x02"

    def test_peek_then_read_returns_same(self):
        buf = make_buffer(b"\xde\xad\xbe\xef")
        peeked = buf.peek_bytes(4)
        read = buf.read_bytes(4)
        assert peeked == read


class TestBufferReadVarint:
    def test_zero(self):
        # zigzag: 0 → encoded as 0x00
        buf = make_buffer(b"\x00")
        assert buf.read_varint() == 0

    def test_positive_one(self):
        # zigzag: 1 → encoded as 0x02
        buf = make_buffer(b"\x02")
        assert buf.read_varint() == 1

    def test_negative_one(self):
        # zigzag: -1 → encoded as 0x01
        buf = make_buffer(b"\x01")
        assert buf.read_varint() == -1

    def test_positive_63(self):
        # zigzag: 63 → encoded as 126 = 0x7e
        buf = make_buffer(b"\x7e")
        assert buf.read_varint() == 63

    def test_negative_64(self):
        # zigzag: -64 → encoded as 127 = 0x7f
        buf = make_buffer(b"\x7f")
        assert buf.read_varint() == -64

    def test_multibyte_positive(self):
        # zigzag: 64 → encoded as 128 = 0x80 0x01 (two bytes)
        buf = make_buffer(b"\x80\x01")
        assert buf.read_varint() == 64

    def test_advances_position_multibyte(self):
        buf = make_buffer(b"\x80\x01\xff")
        buf.read_varint()
        assert buf.position == 2
