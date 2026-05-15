from app.connection import Buffer


def make_buffer(data: bytes) -> Buffer:
    return Buffer(len(data), data)
