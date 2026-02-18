from app.messages import ApiResponse, ApiRequest
from app.protocol import WireProtocol, int_to_bytes, bytes_to_int


class RequestHeader:
    def __init__(
        self,
        api_key: bytes,
        api_version: bytes,
        correlation_id: bytes,
        client_id: bytes,
        tag_buffer: bytes,
    ):
        self.api_key = api_key
        self.api_version = api_version
        self.correlation_id = correlation_id
        self.client_id = client_id
        self.tag_buffer = tag_buffer


class ApiVersionRequestBody:
    def __init__(
        self, client_id: bytes, client_software_version: bytes, tag_buffer: bytes
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
        tag_buffer_raw = self.buffer.read_bytes(
            1
        )  # just one byte here, not sure about other messages
        return RequestHeader(
            api_key_raw,
            api_version_raw,
            correlation_id_raw,
            client_id_raw,
            tag_buffer_raw,
        )

    def get_body(self):
        client_id_size_raw = self.buffer.read_bytes(WireProtocol.LENGTH_BYTES)
        client_id_raw = self.buffer.read_bytes(bytes_to_int(client_id_size_raw))
        client_software_version_size_raw = self.buffer.read_bytes(
            WireProtocol.LENGTH_BYTES
        )
        client_software_version_raw = self.buffer.read_bytes(
            bytes_to_int(client_software_version_size_raw)
        )
        tag_buffer_raw = self.buffer.read_bytes(1)
        return ApiVersionRequestBody(
            client_id_raw, client_software_version_raw, tag_buffer_raw
        )


class ResponseHeader:
    def __init__(self, correlation_id: bytes):
        self.correlation_id = correlation_id

    def get_bytes(self):
        return self.correlation_id


class ApiVersion:
    def __init__(
        self, api_key: bytes, min_version: bytes, max_version: bytes, tag_buffer: bytes
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
        tag_buffer: bytes,
    ):
        self.error = error
        self.api_versions = api_versions
        self.throttle_time = throttle_time
        self.tag_buffer = tag_buffer

    def get_bytes(self) -> bytes:
        # TODO Use Bytes.IO for better performance
        # TODO Must be a wrong type for api versions list
        response = self.error + int_to_bytes(
            len(self.api_versions) + 1, WireProtocol.LENGTH_BYTES
        )
        for api_version in self.api_versions:
            response += api_version.get_bytes()
        response += self.throttle_time + self.tag_buffer
        return response


class ApiVersionRespons(ApiResponse):
    def __init__(self, header: ResponseHeader, body: ApiVersionResponseBody):
        self.header = header
        self.body = body

    def get_bytes(self) -> bytes:
        return self.header.get_bytes() + self.body.get_bytes()

    def get_size(self) -> int:
        return len(self.get_bytes())
