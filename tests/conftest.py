from typing import Optional

from app.connection import Buffer


def make_buffer(data: Optional[bytes]) -> Buffer:
    if data is None:
        return Buffer(0, None)
    return Buffer(len(data), data)
