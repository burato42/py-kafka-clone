import socket  # noqa: F401
from abc import abstractmethod
from typing import Protocol

from app.logging import logger


def bytes_to_int(data: bytes) -> int:
    return int.from_bytes(data, "big")


def int_to_bytes(number: int, size: int) -> bytes:
    return number.to_bytes(size, "big")


class Errors:
    NO_ERROR: int = 0
    UNSUPPORTED_VERSION: int = 35


class WireProtocol:
    # TODO This implementation does't make sense, improve when the implementation is clear
    # 4 bytes is the size of the message in the protocol
    MESSAGE_SIZE_BYTES = 4
    CORRRELATION_ID_BYTES = 4
    REQUEST_API_KEY_BYTES = 2
    REQUEST_API_VERSION_BYTES = 2
    TIME_BYTES = 4
    LENGTH_BYTES = 1

    @staticmethod
    def message_size(size: int) -> bytes:
        return size.to_bytes(WireProtocol.MESSAGE_SIZE_BYTES, 'big')

    @staticmethod
    def response_header_v0(number: int) -> bytes:
        return number.to_bytes(WireProtocol.MESSAGE_SIZE_BYTES, 'big')

    @staticmethod
    def response_header_v2(number: int) -> bytes:
        response: bytes = b""
        response += number.to_bytes(WireProtocol.MESSAGE_SIZE_BYTES, 'big')
        return response

    @staticmethod
    def get_correlation_id(number: int) -> bytes:
        return number.to_bytes(WireProtocol.CORRRELATION_ID_BYTES, 'big')

    @staticmethod
    def get_request_api_key(number: int) -> bytes:
        return number.to_bytes(WireProtocol.REQUEST_API_KEY_BYTES, 'big')

    @staticmethod
    def get_request_api_version(number: int) -> bytes:
        return number.to_bytes(WireProtocol.REQUEST_API_VERSION_BYTES, 'big')

    @staticmethod
    def get_api_key_array_length(number: int) -> bytes:
        return number.to_bytes(1, 'big')

    @staticmethod
    def get_buffer(number: int) -> bytes:
        return number.to_bytes(1, 'big')

    @staticmethod
    def get_time(number: int) -> bytes:
        return number.to_bytes(WireProtocol.TIME_BYTES, 'big')


class Reader:
    def __init__(self, socket_obj: socket.socket):
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
        return self.data[self.position: self.position + n]

    def read_bytes(self, n: int) -> bytes:
        packet = self.peek_bytes(n)
        self.position += n
        return packet


class ApiRequest(Protocol):
    def __init__(self, buffer: Buffer):
        self.buffer = buffer

    @abstractmethod
    def get_header(self):
        pass

    @abstractmethod
    def get_body(self):
        pass


class ApiResponse(Protocol):
    pass


class RequestHeader:
    def __init__(
            self,
            api_key: bytes,
            api_version: bytes,
            correlation_id: bytes,
            client_id: bytes,
            tag_buffer: bytes
    ):
        self.api_key = api_key
        self.api_version = api_version
        self.correlation_id = correlation_id
        self.client_id = client_id
        self.tag_buffer = tag_buffer


class RequestBody:
    def __init__(
            self,
            client_id: bytes,
            client_software_version: bytes,
            tag_buffer: bytes
    ):
        self.client_id = client_id
        self.client_software_version = client_software_version
        self.tag_buffer = tag_buffer


class ApiVersionRequest(ApiRequest):

    def get_header(self):
        api_key_raw = self.buffer.read_bytes(WireProtocol.REQUEST_API_KEY_BYTES)
        api_version_raw = self.buffer.read_bytes(WireProtocol.REQUEST_API_VERSION_BYTES)
        correlation_id_raw = self.buffer.read_bytes(WireProtocol.CORRRELATION_ID_BYTES)
        client_id_size_raw = self.buffer.read_bytes(WireProtocol.LENGTH_BYTES)
        client_id_raw = self.buffer.read_bytes(bytes_to_int(client_id_size_raw))
        tag_buffer_raw = self.buffer.read_bytes(1)  # just one byte here, not sure about other messages
        return RequestHeader(api_key_raw, api_version_raw, correlation_id_raw, client_id_raw, tag_buffer_raw)

    def get_body(self):
        client_id_size_raw = self.buffer.read_bytes(WireProtocol.LENGTH_BYTES)
        client_id_raw = self.buffer.read_bytes(bytes_to_int(client_id_size_raw))
        client_software_version_size_raw = self.buffer.read_bytes(WireProtocol.LENGTH_BYTES)
        client_software_version_raw = self.buffer.read_bytes(bytes_to_int(client_software_version_size_raw))
        tag_buffer_raw = self.buffer.read_bytes(1)
        return RequestBody(client_id_raw, client_software_version_raw, tag_buffer_raw)


APIKEYS: dict[int, type[ApiRequest]] = {
    18: ApiVersionRequest
}


def main():
    print("Logs from your program will appear here!")

    server = socket.create_server(("localhost", 9092), reuse_port=True)
    server.listen()

    while True:
        socket_obj, details = server.accept()
        logger.info("Connection accepted...client details: {}", details)

        reader = Reader(socket_obj)
        buffer = Buffer(*reader.read_full_message())
        raw_api_key = buffer.peek_bytes(WireProtocol.REQUEST_API_KEY_BYTES)

        if (api_key := bytes_to_int(raw_api_key)) in APIKEYS:
            logger.info("Request API key: {}; Request type: {}", api_key, APIKEYS[api_key])
            kls = APIKEYS[api_key]
            request = kls(buffer)
            header: RequestHeader = request.get_header()
            correlation_id = header.correlation_id
            if 4 >= bytes_to_int(header.api_version) >= 0:
                socket_obj.send(WireProtocol.message_size(19))  # Message size, need to add calculation logic
                socket_obj.send(correlation_id)  # Correlation Id
                socket_obj.send(Errors.NO_ERROR.to_bytes(2, 'big'))  # Error
                socket_obj.send(WireProtocol.get_api_key_array_length(2))
                socket_obj.send(header.api_key)
                socket_obj.send(WireProtocol.get_request_api_key(0))  # Min version
                socket_obj.send(WireProtocol.get_request_api_key(4))  # Max version
                socket_obj.send(WireProtocol.get_buffer(0))
                socket_obj.send(WireProtocol.get_time(0))
                socket_obj.send(WireProtocol.get_buffer(0))
            else:
                socket_obj.send(WireProtocol.message_size(6))  # Message size
                socket_obj.send(correlation_id)
                # 2 bytes is the size for the error 
                socket_obj.send(Errors.UNSUPPORTED_VERSION.to_bytes(2, 'big'))
        else:
            logger.info("Unknown API key {}", api_key)
        socket_obj.close()
        logger.info("Connection to client closed")


if __name__ == "__main__":
    main()
