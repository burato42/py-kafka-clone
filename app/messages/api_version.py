from dataclasses import dataclass

from loguru import logger

from app.messages import ApiResponse, ApiRequest
from app.messages.api_key import (
    ApiKey,
    api_version_key,
    describe_topic_partiition_key,
    fetch_key,
    init_producer_id_key,
    list_offsets_key,
    metadata_key,
    produce_key,
)
from app.messages.headers import RequestHeader, ResponseHeaderV0
from app.protocol import Errors, WireProtocol, int_to_bytes, bytes_to_int
from app.tools import read_compact_string


@dataclass
class ApiVersionRequestBody:
    client_id: bytes
    client_software_version: bytes
    tag_buffer: bytes


class ApiVersionRequest(ApiRequest):
    def get_header(self):
        return self.read_header_flexible()

    def get_body(self):
        client_id_raw = read_compact_string(self.buffer)
        client_software_version_raw = read_compact_string(self.buffer)
        tag_buffer_raw = self.buffer.read_bytes(1)
        return ApiVersionRequestBody(
            client_id_raw, client_software_version_raw, tag_buffer_raw
        )


@dataclass
class ApiVersionResponseBody:
    error: bytes
    api_keys: list[ApiKey]
    throttle_time: bytes
    tag_buffer: bytes

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


@dataclass
class ApiVersionResponse(ApiResponse):
    header: ResponseHeaderV0
    body: ApiVersionResponseBody


def handle_api_version_request(request: ApiVersionRequest) -> ApiResponse:
    header: RequestHeader = request.header
    correlation_id = header.correlation_id
    logger.debug("Received API Version request from client ID: {}", header.client_id)
    if 11 >= bytes_to_int(header.api_version) >= 0:
        payload = ApiVersionResponse(
            ResponseHeaderV0(correlation_id),
            ApiVersionResponseBody(
                int_to_bytes(Errors.NO_ERROR, WireProtocol.ERROR_BYTES),
                [
                    api_version_key,
                    describe_topic_partiition_key,
                    fetch_key,
                    init_producer_id_key,
                    list_offsets_key,
                    metadata_key,
                    produce_key,
                ],
                int_to_bytes(0, WireProtocol.TIME_BYTES),
                int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
            ),
        )
    else:
        payload = ApiVersionResponse(
            ResponseHeaderV0(correlation_id),
            ApiVersionResponseBody(
                int_to_bytes(Errors.UNSUPPORTED_VERSION, WireProtocol.ERROR_BYTES),
                [],
                int_to_bytes(0, WireProtocol.TIME_BYTES),
                int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
            ),
        )

    return payload
