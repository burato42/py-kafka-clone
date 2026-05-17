from dataclasses import dataclass

from app.messages import ApiRequest, ApiResponse
from app.messages.headers import RequestHeader, ResponseHeaderV1
from app.protocol import Errors, WireProtocol, int_to_bytes
from app.tools import read_compact_nullable_string, read_uvarint


@dataclass
class InitProducerIdRequestBody:
    transactional_id: bytes
    transaction_timeout_ms: bytes
    producer_id: bytes
    producer_epoch: bytes
    tag_buffer: bytes


class InitProducerIdRequest(ApiRequest):
    header: RequestHeader
    body: InitProducerIdRequestBody

    def get_header(self) -> RequestHeader:
        return self.read_header_flexible()

    def get_body(self) -> InitProducerIdRequestBody:
        transactional_id = read_compact_nullable_string(self.buffer)
        transaction_timeout_ms = self.buffer.read_bytes(4)
        producer_id = self.buffer.read_bytes(8)
        producer_epoch = self.buffer.read_bytes(2)
        tag_buffer = self.buffer.read_bytes(1)
        return InitProducerIdRequestBody(
            transactional_id,
            transaction_timeout_ms,
            producer_id,
            producer_epoch,
            tag_buffer,
        )


@dataclass
class InitProducerIdResponseBody:
    throttle_time_ms: bytes
    error_code: bytes
    producer_id: bytes
    producer_epoch: bytes
    tag_buffer: bytes

    def get_bytes(self) -> bytes:
        return (
            self.throttle_time_ms
            + self.error_code
            + self.producer_id
            + self.producer_epoch
            + self.tag_buffer
        )


@dataclass
class InitProducerIdResponse(ApiResponse):
    header: ResponseHeaderV1
    body: InitProducerIdResponseBody


def handle_init_producer_id_request(request: InitProducerIdRequest) -> InitProducerIdResponse:
    return InitProducerIdResponse(
        ResponseHeaderV1(
            request.header.correlation_id,
            int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
        ),
        InitProducerIdResponseBody(
            int_to_bytes(0, WireProtocol.TIME_BYTES),
            int_to_bytes(Errors.NO_ERROR, WireProtocol.ERROR_BYTES),
            int_to_bytes(0, 8),   # producer_id: INT64
            int_to_bytes(0, 2),   # producer_epoch: INT16
            int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
        ),
    )
