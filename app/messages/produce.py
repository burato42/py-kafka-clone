from dataclasses import dataclass
import os

from loguru import logger

from app.messages import ApiRequest, ApiResponse
from app.messages.cluster_metadata_log import (
    ClusterMetadataLogFile,
    PartitionRecordValue,
    RecordBatch,
    TopicRecordValue,
)
from app.messages.headers import RequestHeader, ResponseHeaderV0, ResponseHeaderV1
from app.protocol import (
    Errors,
    WireProtocol,
    bytes_to_int,
    bytes_to_int_signed,
    int_to_bytes,
    int_to_bytes_signed,
)
from app.tools import (
    log_end_offset,
    read_compact_nullable_string,
    read_compact_string,
    read_uvarint,
    encode_uvarint,
)


@dataclass
class ProducePartition:
    partition_index: bytes
    record_batches: list[RecordBatch]
    record_batches_raw: (
        bytes  # unparsed; populated until full batch parsing is implemented
    )
    tag_buffer: bytes


@dataclass
class ProduceTopic:
    topic_name: bytes  # COMPACT_STRING
    partitions: list[ProducePartition]
    tag_buffer: bytes


@dataclass
class ProduceRequestBody:
    transactional_id: bytes  # compact nullable string
    required_acks: bytes
    timeout: bytes
    topics: list[ProduceTopic]
    tag_buffer: bytes


class ProduceRequest(ApiRequest):
    header: RequestHeader
    body: ProduceRequestBody

    def get_header(self) -> RequestHeader:
        # api_version is at bytes 2–4 of every request
        api_version = bytes_to_int(self.buffer.data[2:4])
        if api_version >= 9:
            return self.read_header_flexible()
        return self.read_header()

    def get_body(self) -> ProduceRequestBody:
        api_version = bytes_to_int(self.header.api_version)
        # TODO Here we can move this version choice on another level. This should make the code cleaner.
        if api_version >= 9:
            return self._get_body_flexible()
        return self._get_body_v3_v8()

    def _get_body_flexible(self) -> ProduceRequestBody:
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
                self.buffer.read_bytes(1)  # partition tag buffer
                partitions.append(
                    ProducePartition(partition_index, [], record_batches_raw, b"\x00")
                )
            self.buffer.read_bytes(1)  # topic tag buffer
            topics.append(ProduceTopic(topic_name, partitions, b"\x00"))
        tag_buffer = self.buffer.read_bytes(1)
        return ProduceRequestBody(
            transactional_id, required_acks, timeout, topics, tag_buffer
        )

    def _get_body_v3_v8(self) -> ProduceRequestBody:
        transactional_id_len = bytes_to_int_signed(self.buffer.read_bytes(2))
        transactional_id = (
            self.buffer.read_bytes(transactional_id_len)
            if transactional_id_len >= 0
            else b""
        )
        required_acks = self.buffer.read_bytes(2)
        timeout = self.buffer.read_bytes(4)
        topics_count = bytes_to_int(self.buffer.read_bytes(4))
        topics = []
        for _ in range(topics_count):
            topic_name_len = bytes_to_int(self.buffer.read_bytes(2))
            topic_name = self.buffer.read_bytes(topic_name_len)
            partitions_count = bytes_to_int(self.buffer.read_bytes(4))
            partitions = []
            for _ in range(partitions_count):
                partition_index = self.buffer.read_bytes(4)
                record_batches_size = bytes_to_int(self.buffer.read_bytes(4))
                record_batches_raw = self.buffer.read_bytes(record_batches_size)
                partitions.append(
                    ProducePartition(partition_index, [], record_batches_raw, b"\x00")
                )
            topics.append(ProduceTopic(topic_name, partitions, b"\x00"))
        return ProduceRequestBody(
            transactional_id, required_acks, timeout, topics, b"\x00"
        )


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

    def get_bytes_v2(self) -> bytes:
        # v2–v4: partition_index(4) error_code(2) base_offset(8) log_append_time(8)
        return (
            self.partition_index
            + self.error_code
            + self.base_offset
            + self.log_append_time
        )

    def get_bytes_v5(self) -> bytes:
        # v5–v7: + log_start_offset(8)
        return self.get_bytes_v2() + self.log_start_offset

    def get_bytes_v8(self) -> bytes:
        # v8: + log_start_offset(8) + record_errors array(4-byte count) + error_message(2-byte len string)
        return (
            self.get_bytes_v5()
            + int_to_bytes(0, 4)          # record_errors: empty array (count=0)
            + int_to_bytes_signed(-1, 2)  # error_message: null string (-1)
        )


@dataclass
class ProduceResponseTopic:
    topic_name: bytes
    partition_responses: list[ProduceResponsePartition]
    tag_buffer: bytes

    def get_bytes(self, api_version: int = 9) -> bytes:
        if api_version >= 9:
            result = self.topic_name + int_to_bytes(
                len(self.partition_responses) + 1, WireProtocol.LENGTH_BYTES
            )
            for response in self.partition_responses:
                result += response.get_bytes()
            result += self.tag_buffer
        else:
            name = self.topic_name
            result = int_to_bytes(len(name), 2) + name
            result += int_to_bytes(len(self.partition_responses), 4)
            for response in self.partition_responses:
                if api_version >= 8:
                    result += response.get_bytes_v8()
                elif api_version >= 5:
                    result += response.get_bytes_v5()
                else:
                    result += response.get_bytes_v2()
        return result


@dataclass
class ProduceResponseBody:
    throttle_time: bytes
    responses: list[ProduceResponseTopic]
    tag_buffer: bytes

    def get_bytes(self, api_version: int = 9) -> bytes:
        if api_version >= 9:
            result = int_to_bytes(len(self.responses) + 1, WireProtocol.LENGTH_BYTES)
            for response in self.responses:
                result += response.get_bytes(api_version=api_version)
            result += self.throttle_time + self.tag_buffer
        else:
            result = int_to_bytes(len(self.responses), 4)
            for response in self.responses:
                result += response.get_bytes(api_version=api_version)
            result += self.throttle_time
        return result


@dataclass
class ProduceResponse(ApiResponse):
    header: ResponseHeaderV0 | ResponseHeaderV1
    body: ProduceResponseBody
    api_version: int = 9

    def get_bytes(self) -> bytes:
        return self.header.get_bytes() + self.body.get_bytes(api_version=self.api_version)



def handle_produce_request(
    request: ProduceRequest,
    cluster_metadata: ClusterMetadataLogFile,
    partition_log_dir: str,
) -> ApiResponse:
    correlation_id = request.header.correlation_id
    api_version = bytes_to_int(request.header.api_version)
    logger.debug("Handling a produce request")
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

    logger.debug("request.body.topics: {}", request.body.topics)
    for tpc in request.body.topics:
        logger.debug("Processing topic {}", tpc.topic_name)
        topic_name = bytes(tpc.topic_name)
        topic_name_encoded = (
            encode_uvarint(len(topic_name) + 1) + topic_name if api_version >= 9 else topic_name
        )
        partition_responses = []
        for part in tpc.partitions:
            partition_id = bytes_to_int(part.partition_index)
            logger.debug(
                "Produce Request topic {}, partition {}", topic_name, partition_id
            )
            is_valid = (
                topic_name in existing_topics
                and (topic_name, partition_id) in valid_partitions
            )
            if is_valid:
                logger.debug("Topic {} and partition {} are valid", topic_name, partition_id)
                log_dir = f"{partition_log_dir}/{topic_name.decode('utf-8')}-{bytes_to_int(part.partition_index)}"
                log_path = f"{log_dir}/00000000000000000000.log"
                os.makedirs(log_dir, exist_ok=True)

                base_offset = log_end_offset(log_path)
                raw = bytearray(part.record_batches_raw)
                raw[0:8] = base_offset.to_bytes(8, "big")
                with open(log_path, "ab") as f:
                    f.write(raw)

                partition_responses.append(
                    ProduceResponsePartition(
                        part.partition_index,
                        int_to_bytes(Errors.NO_ERROR, WireProtocol.ERROR_BYTES),
                        int_to_bytes(base_offset, 8),
                        int_to_bytes_signed(-1, 8),
                        int_to_bytes(0, 8),
                        b"\x00",
                        b"\x00",
                        int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
                    )
                )
            else:
                logger.debug("Topic {} and partition {} are INVALID", topic_name, partition_id)
                partition_responses.append(
                    ProduceResponsePartition(
                        part.partition_index,
                        int_to_bytes(
                            Errors.UNKNOWN_TOPIC_OR_PARTITION, WireProtocol.ERROR_BYTES
                        ),
                        int_to_bytes_signed(-1, 8),
                        int_to_bytes_signed(-1, 8),
                        int_to_bytes_signed(-1, 8),
                        b"\x00",
                        b"\x00",
                        int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
                    )
                )
        responses.append(
            ProduceResponseTopic(
                topic_name_encoded,
                partition_responses,
                int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
            )
        )

    header = (
        ResponseHeaderV1(correlation_id, int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES))
        if api_version >= 9 else ResponseHeaderV0(correlation_id)
    )
    return ProduceResponse(
        header,
        ProduceResponseBody(
            int_to_bytes(0, WireProtocol.TIME_BYTES),
            responses,
            int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
        ),
        api_version=api_version,
    )
