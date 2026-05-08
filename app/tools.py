from typing import Optional

from app.connection import Buffer
from app.protocol import bytes_to_int


# the way of handling compact arrays
def encode_uvarint(value: int) -> bytes:
    result = b""
    while value > 0x7F:
        result += bytes([(value & 0x7F) | 0x80])
        value >>= 7
    result += bytes([value])
    return result

def read_compact_string(buffer: Buffer) -> bytes:
    length = bytes_to_int(buffer.read_bytes(1)) - 1
    return buffer.read_bytes(length) if length > 0 else b""


def read_compact_nullable_string(buffer: Buffer) -> Optional[bytes]:
    length = bytes_to_int(buffer.read_bytes(1)) - 1
    if length < 0:
        return None
    return buffer.read_bytes(length) if length > 0 else b""
