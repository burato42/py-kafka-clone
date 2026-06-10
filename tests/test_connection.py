import asyncio

import pytest

from app.connection import Reader
from tests.conftest import make_buffer


def _make_stream(*chunks: bytes) -> asyncio.StreamReader:
    stream = asyncio.StreamReader()
    for chunk in chunks:
        stream.feed_data(chunk)
    stream.feed_eof()
    return stream


@pytest.mark.asyncio
class TestReader:
    async def test_reads_full_message(self):
        payload = b"hello"
        stream = _make_stream((5).to_bytes(4, "big"), payload)
        size, data = await Reader(stream).read_full_message()
        assert size == 5
        assert data == payload

    async def test_reads_full_message_single_feed(self):
        # size prefix and payload arrive in one chunk (common in practice)
        payload = b"world"
        combined = (5).to_bytes(4, "big") + payload
        stream = _make_stream(combined)
        size, data = await Reader(stream).read_full_message()
        assert size == 5
        assert data == payload

    async def test_raises_on_eof_during_size(self):
        stream = asyncio.StreamReader()
        stream.feed_eof()
        with pytest.raises(asyncio.IncompleteReadError):
            await Reader(stream).read_full_message()

    async def test_raises_on_eof_during_payload(self):
        # Send size prefix but close before the payload arrives
        stream = asyncio.StreamReader()
        stream.feed_data((10).to_bytes(4, "big"))
        stream.feed_eof()
        with pytest.raises(asyncio.IncompleteReadError):
            await Reader(stream).read_full_message()


class TestBufferInit:
    def test_none_data_defaults_to_empty_bytearray(self):
        buf = make_buffer(None)
        assert buf.data == bytearray()
        assert buf.position == 0
        assert buf.message_size == 0
