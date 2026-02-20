from app.messages import ApiResponse, ApiRequest
from app.messages.api_key import ApiKey
from app.messages.headers import ResponseHeaderV0, RequestHeaderV2
from app.protocol import WireProtocol, int_to_bytes, bytes_to_int


class ApiVersionRequestBody:
    def __init__(
        self, client_id: bytes, client_software_version: bytes, tag_buffer: bytes
    ):
        self.client_id = client_id
        self.client_software_version = client_software_version
        self.tag_buffer = tag_buffer


class ApiVersionRequest(ApiRequest):
    
    def get_header(self):
        return self.get_header_v2()
    
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


class ApiVersionResponseBody:
    def __init__(
        self,
        error: bytes,
        api_keys: list[ApiKey],
        throttle_time: bytes,
        tag_buffer: bytes,
    ):
        self.error = error
        self.api_keys = api_keys
        self.throttle_time = throttle_time
        self.tag_buffer = tag_buffer

    def get_bytes(self) -> bytes:
        # TODO Use BytesIO for better performance (An improvement to test)
        # TODO Must be a wrong type for api versions list, we need to check the size dynamically
        response = self.error + int_to_bytes(
            len(self.api_keys) + 1, WireProtocol.LENGTH_BYTES
        )
        for api_version in self.api_keys:
            response += api_version.get_bytes()
        response += self.throttle_time + self.tag_buffer
        return response


class ApiVersionResponse(ApiResponse):
    def __init__(self, header: ResponseHeaderV0, body: ApiVersionResponseBody):
        self.header = header
        self.body = body

