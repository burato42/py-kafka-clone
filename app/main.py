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
    # Byte size sonstants
    MESSAGE_SIZE_BYTES = 4
    CORRRELATION_ID_BYTES = 4
    REQUEST_API_KEY_BYTES = 2
    REQUEST_API_VERSION_BYTES = 2
    TIME_BYTES = 4
    LENGTH_BYTES = 1
    TAG_BUFFER_BYTES = 1
    ERROR_BYTES = 2


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


class ApiVersionRequestBody:
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
        return ApiVersionRequestBody(client_id_raw, client_software_version_raw, tag_buffer_raw)


class ResponseHeader:
    def __init__(
            self,
            correlation_id: bytes
    ):
        self.correlation_id = correlation_id

    def get_bytes(self):
        return self.correlation_id


class ApiVersion:
    def __init__(
            self,
            api_key: bytes,
            min_version: bytes,
            max_version: bytes,
            tag_buffer: bytes
    ):
        self.api_key = api_key
        self.min_version = min_version
        self.max_version = max_version
        self.tag_buffer = tag_buffer

    def get_bytes(self) -> bytes:
        return self.api_key + self.min_version + self.max_version + self.tag_buffer


class ApiVersionResponseBody:
    def __init__(
            self,
            error: bytes,
            api_versions: list[ApiVersion],
            throttle_time: bytes,
            tag_buffer: bytes
    ):
        self.error = error
        self.api_versions = api_versions
        self.throttle_time = throttle_time
        self.tag_buffer = tag_buffer

    def get_bytes(self) -> bytes:
        response = self.error + int_to_bytes(len(self.api_versions) + 1, WireProtocol.LENGTH_BYTES)
        for api_version in self.api_versions:
            response += api_version.get_bytes()
        response += self.throttle_time + self.tag_buffer
        return response


class ApiVersionRespons(ApiResponse):
    def __init__(
            self,
            header: ResponseHeader,
            body: ApiVersionResponseBody
    ):
        self.header = header
        self.body = body

    def get_bytes(self) -> bytes:
        return self.header.get_bytes() + self.body.get_bytes()

    def get_size(self) -> int:
        return len(self.get_bytes())


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
                payload = ApiVersionRespons(
                    ResponseHeader(correlation_id),
                    ApiVersionResponseBody(
                        int_to_bytes(Errors.NO_ERROR, WireProtocol.ERROR_BYTES),
                        [ApiVersion(
                            raw_api_key,
                            int_to_bytes(0, WireProtocol.REQUEST_API_VERSION_BYTES),
                            int_to_bytes(4, WireProtocol.REQUEST_API_VERSION_BYTES),
                            int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
                        )],
                        int_to_bytes(0, WireProtocol.TIME_BYTES),
                        int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES)
                    )
                )
                socket_obj.send(int_to_bytes(payload.get_size(), WireProtocol.MESSAGE_SIZE_BYTES))
                socket_obj.send(payload.get_bytes())
            else:
                payload = ApiVersionRespons(
                    ResponseHeader(correlation_id),
                    ApiVersionResponseBody(
                        int_to_bytes(Errors.UNSUPPORTED_VERSION, WireProtocol.ERROR_BYTES),
                        [],
                        int_to_bytes(0, WireProtocol.TIME_BYTES),
                        int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES)
                    )
                )
                socket_obj.send(int_to_bytes(payload.get_size(), WireProtocol.MESSAGE_SIZE_BYTES))
                socket_obj.send(payload.get_bytes())

        else:
            logger.info("Unknown API key {}", api_key)
        socket_obj.close()
        logger.info("Connection to client closed")


if __name__ == "__main__":
    main()
