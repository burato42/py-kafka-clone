from socket import socket

from app.protocol import WireProtocol


class Reader:
    def __init__(self, socket_obj: socket):
        self.socket_obj = socket_obj

    def read_full_message(self) -> tuple[int, bytes]:
        raw_size = self._recv_all(WireProtocol.MESSAGE_SIZE_BYTES)
        message_size = int.from_bytes(raw_size, "big")
        payload = self._recv_all(message_size)
        return message_size, payload

    def _recv_all(self, n: int) -> bytes:
        data = bytearray()
        while len(data) < n:
            packet = self.socket_obj.recv(n - len(data))
            if not packet:
                raise EOFError("Socket closed before all bytes were read")
            data.extend(packet)
        return data


class Buffer:
    def __init__(self, message_size: int, data: bytes):
        self.data = data or bytearray()
        self.position = 0
        self.message_size = message_size

    def peek_bytes(self, n: int) -> bytes:
        return self.data[self.position : self.position + n]

    def read_bytes(self, n: int) -> bytes:
        packet = self.peek_bytes(n)
        self.position += n
        return packet

    def read_varint(self) -> int:
        """Read a zigzag-encoded varint and return the decoded signed integer."""
        raw = 0
        shift = 0
        while True:
            b = self.data[self.position]
            self.position += 1
            raw |= (b & 0x7F) << shift
            shift += 7
            if not (b & 0x80):
                break
        return (raw >> 1) ^ -(raw & 1)
