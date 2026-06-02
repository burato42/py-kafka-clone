import os
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


def read_uvarint(buffer: Buffer) -> int:
    result = 0
    shift = 0
    while True:
        b = bytes_to_int(buffer.read_bytes(1))
        result |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            break
    return result


def read_compact_string(buffer: Buffer) -> bytes:
    length = bytes_to_int(buffer.read_bytes(1)) - 1
    return buffer.read_bytes(length) if length > 0 else b""


def read_compact_nullable_string(buffer: Buffer) -> Optional[bytes]:
    length = bytes_to_int(buffer.read_bytes(1)) - 1
    if length < 0:
        return None
    return buffer.read_bytes(length) if length > 0 else b""


def log_end_offset(log_path: str) -> int:
    """Return the next offset after the last record in a partition log (the LEO)."""
    if not os.path.exists(log_path):
        return 0
    with open(log_path, "rb") as f:
        data = f.read()
    offset = 0
    pos = 0
    while pos + 12 <= len(data):
        base_offset = int.from_bytes(data[pos : pos + 8], "big")
        batch_length = int.from_bytes(data[pos + 8 : pos + 12], "big")
        record_count_pos = pos + 57
        if record_count_pos + 4 > len(data):
            break
        record_count = int.from_bytes(data[record_count_pos : record_count_pos + 4], "big")
        offset = base_offset + record_count
        pos += 8 + 4 + batch_length
    return offset


def read_log_from_offset(log_path: str, fetch_offset: int) -> bytes:
    """Return raw log bytes for all batches whose base_offset >= fetch_offset."""
    if not os.path.exists(log_path):
        return b""
    with open(log_path, "rb") as f:
        data = f.read()
    pos = 0
    while pos + 12 <= len(data):
        base_offset = int.from_bytes(data[pos : pos + 8], "big")
        batch_length = int.from_bytes(data[pos + 8 : pos + 12], "big")
        record_count_pos = pos + 57
        if record_count_pos + 4 > len(data):
            break
        record_count = int.from_bytes(data[record_count_pos : record_count_pos + 4], "big")
        next_pos = pos + 8 + 4 + batch_length
        if base_offset + record_count > fetch_offset:
            return data[pos:]
        pos = next_pos
    return b""
