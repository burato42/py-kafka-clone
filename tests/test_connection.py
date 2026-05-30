from unittest.mock import MagicMock

import pytest

from app.connection import Reader
from tests.conftest import make_buffer


class TestReader:
    def _make_socket(self, chunks: list[bytes]) -> MagicMock:
        sock = MagicMock()
        sock.recv.side_effect = chunks
        return sock

    def test_reads_full_message_single_recv(self):
        # 4-byte size prefix (value=5) followed by 5-byte payload, each in one recv
        size_bytes = (5).to_bytes(4, "big")
        payload = b"hello"
        sock = self._make_socket([size_bytes, payload])
        reader = Reader(sock)
        size, data = reader.read_full_message()
        assert size == 5
        assert data == bytearray(payload)

    def test_reads_full_message_fragmented_recv(self):
        # Size arrives in two fragments, then payload in two fragments
        size_bytes = (4).to_bytes(4, "big")
        sock = self._make_socket(
            [size_bytes[:2], size_bytes[2:], b"ab", b"cd"]
        )
        reader = Reader(sock)
        size, data = reader.read_full_message()
        assert size == 4
        assert data == bytearray(b"abcd")

    def test_raises_eof_when_socket_closed_during_size(self):
        sock = MagicMock()
        sock.recv.return_value = b""  # closed immediately
        reader = Reader(sock)
        with pytest.raises(EOFError):
            reader.read_full_message()

    def test_raises_eof_when_socket_closed_during_payload(self):
        size_bytes = (10).to_bytes(4, "big")
        sock = MagicMock()
        # First call returns the size, second returns empty (closed)
        sock.recv.side_effect = [size_bytes, b""]
        reader = Reader(sock)
        with pytest.raises(EOFError):
            reader.read_full_message()


class TestBufferInit:
    def test_none_data_defaults_to_empty_bytearray(self):
        buf = make_buffer(None)
        assert buf.data == bytearray()
        assert buf.position == 0
        assert buf.message_size == 0
