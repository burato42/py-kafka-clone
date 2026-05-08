from dataclasses import dataclass
from typing import Optional

from loguru import logger

from app.messages import ApiRequest, ApiResponse
from app.messages.cluster_metadata_log import ClusterMetadataLogFile, TopicRecordValue
from app.messages.headers import ResponseHeaderV1
from app.protocol import Errors, WireProtocol, bytes_to_int, int_to_bytes
from app.tools import encode_uvarint, read_compact_nullable_string, read_compact_string


@dataclass
class FetchPartition:
    partition: bytes
    current_leader_epoch: bytes
    fetch_offset: bytes
    last_fetched_epoch: bytes
    log_start_offset: bytes
    partition_max_bytes: bytes


@dataclass
class FetchTopic:
    topic_id: bytes
    partitions: list[FetchPartition]


@dataclass
class ForgottenTopic:
    topic_id: bytes
    partitions: list[bytes]


@dataclass
class FetchRequestBody:
    max_wait_ms: bytes
    min_bytes: bytes
    max_bytes: bytes
    isolation_level: bytes
    session_id: bytes
    session_epoch: bytes
    topics: list[FetchTopic]
    forgotten_topics_data: list[ForgottenTopic]
    rack_id: bytes
    cluster_id: Optional[bytes]
    replica_id: Optional[bytes]
    replica_epoch: Optional[bytes]


class FetchRequest(ApiRequest):
    def get_header(self):
        return self.get_header_v2()

    def get_body(self) -> FetchRequestBody:
        max_wait_ms = self.buffer.read_bytes(4)
        min_bytes = self.buffer.read_bytes(4)
        max_bytes = self.buffer.read_bytes(4)
        isolation_level = self.buffer.read_bytes(1)
        session_id = self.buffer.read_bytes(4)
        session_epoch = self.buffer.read_bytes(4)

        topics_count = bytes_to_int(self.buffer.read_bytes(1)) - 1
        topics = []
        for _ in range(topics_count):
            topic_id = self.buffer.read_bytes(16)
            partitions_count = bytes_to_int(self.buffer.read_bytes(1)) - 1
            partitions = []
            for _ in range(partitions_count):
                partition = self.buffer.read_bytes(4)
                current_leader_epoch = self.buffer.read_bytes(4)
                fetch_offset = self.buffer.read_bytes(8)
                last_fetched_epoch = self.buffer.read_bytes(4)
                log_start_offset = self.buffer.read_bytes(8)
                partition_max_bytes = self.buffer.read_bytes(4)
                self.buffer.read_bytes(1)  # partition tag buffer
                partitions.append(FetchPartition(
                    partition,
                    current_leader_epoch,
                    fetch_offset,
                    last_fetched_epoch,
                    log_start_offset,
                    partition_max_bytes,
                ))
            self.buffer.read_bytes(1)  # topic tag buffer
            topics.append(FetchTopic(topic_id, partitions))

        forgotten_count = bytes_to_int(self.buffer.read_bytes(1)) - 1
        forgotten_topics_data = []
        for _ in range(forgotten_count):
            topic_id = self.buffer.read_bytes(16)
            fp_count = bytes_to_int(self.buffer.read_bytes(1)) - 1
            fp_partitions = [self.buffer.read_bytes(4) for _ in range(fp_count)]
            self.buffer.read_bytes(1)  # forgotten topic tag buffer
            forgotten_topics_data.append(ForgottenTopic(topic_id, fp_partitions))

        rack_id = read_compact_string(self.buffer)

        # Tagged fields
        cluster_id: Optional[bytes] = None
        replica_id: Optional[bytes] = None
        replica_epoch: Optional[bytes] = None

        num_tagged_fields = bytes_to_int(self.buffer.read_bytes(1))
        for _ in range(num_tagged_fields):
            tag = bytes_to_int(self.buffer.read_bytes(1))
            size = bytes_to_int(self.buffer.read_bytes(1))
            if tag == 0:  # cluster_id: COMPACT_NULLABLE_STRING
                cluster_id = read_compact_nullable_string(self.buffer)
            elif tag == 1:  # replica_state: replica_id (INT32) + replica_epoch (INT64)
                replica_id = self.buffer.read_bytes(4)
                replica_epoch = self.buffer.read_bytes(8)
            else:
                self.buffer.read_bytes(size)

        return FetchRequestBody(
            max_wait_ms,
            min_bytes,
            max_bytes,
            isolation_level,
            session_id,
            session_epoch,
            topics,
            forgotten_topics_data,
            rack_id,
            cluster_id,
            replica_id,
            replica_epoch,
        )


@dataclass
class FetchResponsePartition:
    partition_index: bytes   # INT32
    error_code: bytes        # INT16
    high_watermark: bytes    # INT64
    last_stable_offset: bytes  # INT64
    log_start_offset: bytes    # INT64
    aborted_transactions: bytes # compact array (empty = \x01)
    preferred_read_replica: bytes #INT32
    records: bytes # compact nullable bytes (null = \x00)
    tag_buffer: bytes

    def get_bytes(self) -> bytes:
        if self.records == b"\x00":
            records_bytes = b"\x00"
        else:
            # compact bytes: uvarint(len+1) followed by data
            n = len(self.records)
            records_bytes = encode_uvarint(n + 1) + self.records
        return (
            self.partition_index
            + self.error_code
            + self.high_watermark
            + self.last_stable_offset
            + self.log_start_offset
            + b"\x01"    # aborted_transactions: empty compact array
            + int_to_bytes(0xFFFFFFFF, 4)  # preferred_read_replica: -1 (none)
            + records_bytes
            + b"\x00"    # tag_buffer
        )


@dataclass
class FetchResponseTopic:
    topic_id: bytes
    partitions: list[FetchResponsePartition]

    def get_bytes(self) -> bytes:
        result = self.topic_id + int_to_bytes(len(self.partitions) + 1, WireProtocol.LENGTH_BYTES)
        for part in self.partitions:
            result += part.get_bytes()
        result += b"\x00"  # tag_buffer
        return result


@dataclass
class FetchResponseBody:
    throttle_time: bytes
    error_code: bytes
    session_id: bytes
    responses: list[FetchResponseTopic]
    tag_buffer: bytes

    def get_bytes(self) -> bytes:
        result = (
            self.throttle_time
            + self.error_code
            + self.session_id
            + int_to_bytes(len(self.responses) + 1, WireProtocol.LENGTH_BYTES)
        )
        for response in self.responses:
            result += response.get_bytes()
        result += self.tag_buffer
        return result


@dataclass
class FetchResponse(ApiResponse):
    header: ResponseHeaderV1
    body: FetchResponseBody


def handle_fetch_request(
        request: FetchRequest, 
        cluster_metadata: ClusterMetadataLogFile,
    ) -> ApiResponse:
    
    existing_topics = dict()
    topic_partitions = dict()
    for record_batch in cluster_metadata.record_batches:
        for record in record_batch.records:
            val = record.value
            if isinstance(val, TopicRecordValue):
                existing_topics[bytes(val.topic_uuid)] = val.topic_name
                topic_partitions[bytes(val.topic_uuid)] = []


    correlation_id = request.header.correlation_id
    responses = []

    
    for tpc in request.body.topics:
        if bytes(tpc.topic_id) in existing_topics:
            topic_name = existing_topics[bytes(tpc.topic_id)].decode("utf-8")
            partitions = []
            for fetch_partition in tpc.partitions:
                partition_idx = bytes_to_int(fetch_partition.partition)
                logger.debug("Found partition: {}, topic is {}", partition_idx, topic_name)
                # TODO Move file template to the configuration
                log_path = f"/tmp/kraft-combined-logs/{topic_name}-{partition_idx}/00000000000000000000.log"
                try:
                    with open(log_path, "rb") as f:
                        log_data = f.read()
                except OSError:
                    log_data = None
                partitions.append(FetchResponsePartition(
                    fetch_partition.partition,
                    int_to_bytes(Errors.NO_ERROR, 2),
                    int_to_bytes(0, 8),
                    int_to_bytes(0, 8),
                    int_to_bytes(0, 8),
                    b"\x01",
                    int_to_bytes(0xFFFFFFFF, 4),
                    log_data if log_data is not None else b"\x00",
                    b"\x00",
                ))
            responses.append(FetchResponseTopic(tpc.topic_id, partitions))
        else:
            responses.append(
                FetchResponseTopic(
                    tpc.topic_id,
                    [
                        FetchResponsePartition(
                            int_to_bytes(0, 4),
                            int_to_bytes(Errors.UNKNOWN_TOPIC_ID, 2),
                            int_to_bytes(0, 8),
                            int_to_bytes(0, 8),
                            int_to_bytes(0, 8),
                            b"\x01",
                            int_to_bytes(0xFFFFFFFF, 4),
                            b"\x00",
                            b"\x00",
                        )
                    ],
                )
            )
        
    return FetchResponse(
        ResponseHeaderV1(
            correlation_id,
            int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
        ),
        FetchResponseBody(
            int_to_bytes(0, WireProtocol.TIME_BYTES),
            int_to_bytes(Errors.NO_ERROR, WireProtocol.ERROR_BYTES),
            int_to_bytes(0, 4),
            responses,
            int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
        ),
    )
