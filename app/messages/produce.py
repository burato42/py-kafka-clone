from dataclasses import dataclass

from loguru import logger

from app.messages import ApiRequest, ApiResponse
from app.messages.cluster_metadata_log import ClusterMetadataLogFile, PartitionRecordValue, RecordBatch, TopicRecordValue
from app.messages.headers import RequestHeaderV2, ResponseHeaderV1
from app.protocol import Errors, WireProtocol, bytes_to_int, int_to_bytes, int_to_bytes_signed
from app.tools import encode_uvarint, read_compact_nullable_string, read_compact_string, read_uvarint


@dataclass
class ProducePartition:
    partition_index: bytes
    record_batches: list[RecordBatch]
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
    header: RequestHeaderV2
    body: ProduceRequestBody

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
                record_batches_size = read_uvarint(self.buffer) - 1
                record_batches_raw = self.buffer.read_bytes(record_batches_size)
                record_batches = []
                self.buffer.read_bytes(1)  # partition tag buffer
                partitions.append(ProducePartition(partition_index, record_batches, record_batches_raw, b"\x00"))
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
    partition_log_dir: str,
) -> ApiResponse:
    correlation_id = request.header.correlation_id

    topic_uuid_to_name: dict[bytes, bytes] = {}
    valid_partitions: set[tuple[bytes, int]] = set()
    for record_batch in cluster_metadata.record_batches:
        for record in record_batch.records:
            val = record.value
            if isinstance(val, TopicRecordValue):
                topic_uuid_to_name[bytes(val.topic_uuid)] = bytes(val.topic_name)
            elif isinstance(val, PartitionRecordValue):
                topic_name = topic_uuid_to_name.get(bytes(val.topic_uuid))
                if topic_name is not None:
                    valid_partitions.add((topic_name, bytes_to_int(val.partition_id)))
    
    existing_topics = set(topic_uuid_to_name.values())
    logger.debug("Existing topics: {}", existing_topics)
    logger.debug("Valid partitions: {}", valid_partitions)
    responses = []

    for tpc in request.body.topics:
        topic_name = bytes(tpc.topic_name)
        topic_name_encoded = encode_uvarint(len(topic_name) + 1) + topic_name
        partition_responses = []
        for part in tpc.partitions:
            partition_id = bytes_to_int(part.partition_index)
            logger.debug("Produce Request topic {}, partition {}", topic_name, partition_id)
            is_valid = (
                topic_name in existing_topics
                and (topic_name, partition_id) in valid_partitions
            )
            if is_valid:
                partition_responses.append(ProduceResponsePartition(
                    part.partition_index,
                    int_to_bytes(Errors.NO_ERROR, WireProtocol.ERROR_BYTES),
                    int_to_bytes(0, 8),
                    int_to_bytes_signed(-1, 8),
                    int_to_bytes(0, 8),
                    b"\x00",
                    b"\x00",
                    int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
                ))
                log_path = f"{partition_log_dir}/{topic_name.decode('utf-8')}-{bytes_to_int(part.partition_index)}/00000000000000000000.log"

                with open(log_path, "ab") as f:
                    f.write(part.record_batches_raw)
            else:
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
