from dataclasses import dataclass
from typing import Optional

from app.messages import ApiRequest, ApiResponse
from app.messages.cluster_metadata_log import ClusterMetadataLogFile
from app.messages.headers import RequestHeaderV2, ResponseHeaderV1
from app.protocol import Errors, WireProtocol, bytes_to_int, int_to_bytes, int_to_bytes_signed
from app.tools import encode_uvarint, read_compact_nullable_string, read_compact_string


@dataclass
class ProduceRecordBatch:
    base_offset: bytes
    batch_size: bytes
    partition_leader_epoch: bytes
    magic_byte: bytes
    crc: bytes
    attributes: bytes
    last_offset_delta: bytes
    first_timestamp: bytes
    last_timestamp: bytes
    producer_id: bytes
    producer_epoch: bytes
    base_sequence: bytes
    records: bytes  # raw bytes of the records array


@dataclass
class ProducePartition:
    partition_index: bytes
    record_batches: list[ProduceRecordBatch]
    record_batches_raw: bytes  # unparsed; populated until full batch parsing is implemented
    tag_buffer: bytes


@dataclass
class ProduceTopic:
    topic_name: bytes # COMPACT_STRING
    partitions: list[ProducePartition]
    tag_buffer: bytes


@dataclass
class ProduceRequestBody:
    transactional_id: bytes # compact nullable string
    required_acks: bytes
    timeout: bytes
    topics: list[ProduceTopic]
    tag_buffer: bytes


class ProduceRequest(ApiRequest):
    def get_header(self) -> RequestHeaderV2:
        return self.get_header_v2()

    def get_body(self) -> ProduceRequestBody:
        transactional_id = read_compact_nullable_string(self.buffer)
        required_acks = self.buffer.read_bytes(2)
        timeout = self.buffer.read_bytes(4)

        topics_count = bytes_to_int(self.buffer.read_bytes(1)) - 1
        topics = []
        for _ in range(topics_count):
            topic_name = read_compact_string(self.buffer)
            partitions_count = bytes_to_int(self.buffer.read_bytes(1)) - 1
            partitions = []
            for _ in range(partitions_count):
                partition_index = self.buffer.read_bytes(4)
                record_batches_size = bytes_to_int(self.buffer.read_bytes(4))
                record_batches_raw = self.buffer.read_bytes(record_batches_size)
                self.buffer.read_bytes(1)  # partition tag buffer
                partitions.append(ProducePartition(partition_index, [], record_batches_raw, b"\x00"))
            self.buffer.read_bytes(1)  # topic tag buffer
            topics.append(ProduceTopic(topic_name, partitions, b"\x00"))

        tag_buffer = self.buffer.read_bytes(1)
        return ProduceRequestBody(transactional_id, required_acks, timeout, topics, tag_buffer)


@dataclass
class ProduceResponsePartition:
    partition_index: bytes
    error_code: bytes
    base_offset: bytes
    log_append_time: bytes
    log_start_offset: bytes
    record_errors: bytes  # compact array (empty = \x01, null = \x00)
    error_message: bytes  # compact nullable string (null = \x00)
    tag_buffer: bytes

    def get_bytes(self) -> bytes:
        if self.record_errors == b"\x00":
            record_errors_bytes = b"\x01"  # empty compact array
        else:
            n = len(self.record_errors)
            record_errors_bytes = encode_uvarint(n + 1) + self.record_errors
        return (
            self.partition_index
            + self.error_code
            + self.base_offset
            + self.log_append_time
            + self.log_start_offset
            + record_errors_bytes
            + self.error_message
            + self.tag_buffer
        )
    

@dataclass
class ProduceResponseTopic:
    topic_name: bytes
    partition_responses: list[ProduceResponsePartition]
    tag_buffer: bytes

    def get_bytes(self) -> bytes:
        result = (
            self.topic_name 
            + int_to_bytes(len(self.partition_responses) + 1, WireProtocol.LENGTH_BYTES)
        )
        for response in self.partition_responses:
            result += response.get_bytes()
        result += self.tag_buffer
        return result          


@dataclass
class ProduceResponseBody:
    throttle_time: bytes
    responses: list[ProduceResponseTopic]
    tag_buffer: bytes

    def get_bytes(self) -> bytes:
        result = int_to_bytes(len(self.responses) + 1, WireProtocol.LENGTH_BYTES)
        for response in self.responses:
            result += response.get_bytes()
        result += self.throttle_time + self.tag_buffer
        return result
    

@dataclass
class ProduceResponse(ApiResponse):
    header: ResponseHeaderV1
    body: ProduceResponseBody



def handle_produce_request(
    request: ProduceRequest,
    cluster_metadata: ClusterMetadataLogFile,
) -> ApiResponse:
    correlation_id = request.header.correlation_id
    responses = []

    for tpc in request.body.topics:
        partition_responses = []
        for part in tpc.partitions:
            partition_responses.append(ProduceResponsePartition(
                part.partition_index,
                int_to_bytes(Errors.UNKNOWN_TOPIC_OR_PARTITION, WireProtocol.ERROR_BYTES),
                int_to_bytes_signed(-1, 8),
                int_to_bytes_signed(-1, 8),
                int_to_bytes_signed(-1, 8),
                b"\x00",
                b"\x00",
                int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
            ))
        topic_name_encoded = encode_uvarint(len(tpc.topic_name) + 1) + tpc.topic_name
        responses.append(ProduceResponseTopic(
            topic_name_encoded,
            partition_responses,
            int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
        ))

    return ProduceResponse(
        ResponseHeaderV1(
            correlation_id,
            int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
        ),
        ProduceResponseBody(
            int_to_bytes(0, WireProtocol.TIME_BYTES),
            responses,
            int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
        ),
    )
