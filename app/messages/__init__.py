from abc import abstractmethod
from typing import Protocol

from app.connection import Buffer
from app.messages.headers import RequestHeaderV2
from app.protocol import WireProtocol, bytes_to_int


# TODO Fix OOP structure which is a messy right now


class ApiRequest(Protocol):
    def __init__(self, buffer: Buffer):
        self.buffer = buffer
        self.header = self.get_header()
        self.body = self.get_body()

    @abstractmethod
    def get_header(self):
        pass

    def get_header_v2(self):
        api_key_raw = self.buffer.read_bytes(WireProtocol.REQUEST_API_KEY_BYTES)
        api_version_raw = self.buffer.read_bytes(WireProtocol.REQUEST_API_VERSION_BYTES)
        correlation_id_raw = self.buffer.read_bytes(WireProtocol.CORRRELATION_ID_BYTES)
        client_id_size_raw = self.buffer.read_bytes(WireProtocol.CLIENT_ID_BYTES)
        client_id_raw = self.buffer.read_bytes(bytes_to_int(client_id_size_raw))
        tag_buffer_raw = self.buffer.read_bytes(WireProtocol.TAG_BUFFER_BYTES)
        return RequestHeaderV2(
            api_key_raw,
            api_version_raw,
            correlation_id_raw,
            client_id_raw,
            tag_buffer_raw,
        )

    @abstractmethod
    def get_body(self):
        pass


class ApiResponse(Protocol):
    def get_bytes(self) -> bytes:
        return self.header.get_bytes() + self.body.get_bytes()

    def get_size(self) -> int:
        return len(self.get_bytes())
