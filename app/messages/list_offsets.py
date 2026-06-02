from dataclasses import dataclass

from loguru import logger

from app.messages import ApiRequest, ApiResponse
from app.messages.cluster_metadata_log import (
    ClusterMetadataLogFile,
    PartitionRecordValue,
    TopicRecordValue,
)
from app.messages.headers import RequestHeader, ResponseHeaderV0
from app.protocol import (
    Errors,
    WireProtocol,
    bytes_to_int,
    bytes_to_int_signed,
    int_to_bytes,
    int_to_bytes_signed,
)
from app.tools import log_end_offset


@dataclass
class ListOffsetsPartition:
    partition_index: bytes
    current_leader_epoch: bytes  # present in v4+
    timestamp: bytes  # INT64; -2=earliest, -1=latest


@dataclass
class ListOffsetsTopic:
    name: bytes
    partitions: list[ListOffsetsPartition]


@dataclass
class ListOffsetsRequestBody:
    replica_id: bytes
    isolation_level: bytes  # present in v2+
    topics: list[ListOffsetsTopic]


class ListOffsetsRequest(ApiRequest):
    def get_header(self) -> RequestHeader:
        return self.read_header()

    def get_body(self) -> ListOffsetsRequestBody:
        api_version = bytes_to_int(self.header.api_version)
        replica_id = self.buffer.read_bytes(4)
        isolation_level = self.buffer.read_bytes(1) if api_version >= 2 else b"\x00"
        topics_count = bytes_to_int(self.buffer.read_bytes(4))
        topics = []
        for _ in range(topics_count):
            name_len = bytes_to_int(self.buffer.read_bytes(2))
            name = self.buffer.read_bytes(name_len)
            partitions_count = bytes_to_int(self.buffer.read_bytes(4))
            partitions = []
            for _ in range(partitions_count):
                partition_index = self.buffer.read_bytes(4)
                current_leader_epoch = (
                    self.buffer.read_bytes(4) if api_version >= 4 else b"\x00\x00\x00\x00"
                )
                timestamp = self.buffer.read_bytes(8)
                partitions.append(
                    ListOffsetsPartition(partition_index, current_leader_epoch, timestamp)
                )
            topics.append(ListOffsetsTopic(name, partitions))
        return ListOffsetsRequestBody(replica_id, isolation_level, topics)


@dataclass
class ListOffsetsResponsePartition:
    partition_index: bytes
    error_code: bytes
    timestamp: bytes   # INT64
    offset: bytes      # INT64
    leader_epoch: bytes  # INT32, present in v4+

    def get_bytes(self, api_version: int) -> bytes:
        result = self.partition_index + self.error_code + self.timestamp + self.offset
        if api_version >= 4:
            result += self.leader_epoch
        return result


@dataclass
class ListOffsetsResponseTopic:
    name: bytes
    partitions: list[ListOffsetsResponsePartition]

    def get_bytes(self, api_version: int) -> bytes:
        result = int_to_bytes(len(self.name), 2) + self.name
        result += int_to_bytes(len(self.partitions), 4)
        for p in self.partitions:
            result += p.get_bytes(api_version)
        return result


@dataclass
class ListOffsetsResponseBody:
    throttle_time: bytes
    topics: list[ListOffsetsResponseTopic]
    api_version: int

    def get_bytes(self) -> bytes:
        result = self.throttle_time
        result += int_to_bytes(len(self.topics), 4)
        for t in self.topics:
            result += t.get_bytes(self.api_version)
        return result


@dataclass
class ListOffsetsResponse(ApiResponse):
    header: ResponseHeaderV0
    body: ListOffsetsResponseBody


def handle_list_offsets_request(
    request: ListOffsetsRequest,
    cluster_metadata: ClusterMetadataLogFile,
    partition_log_dir: str,
) -> ApiResponse:
    api_version = bytes_to_int(request.header.api_version)
    correlation_id = request.header.correlation_id
    logger.debug("Handling ListOffsets request v{}", api_version)

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

    response_topics = []
    for topic in request.body.topics:
        topic_name = bytes(topic.name)
        partition_responses = []
        for part in topic.partitions:
            partition_id = bytes_to_int(part.partition_index)
            is_valid = (
                topic_name in existing_topics
                and (topic_name, partition_id) in valid_partitions
            )
            if not is_valid:
                logger.debug("ListOffsets: unknown topic/partition {}/{}", topic_name, partition_id)
                partition_responses.append(
                    ListOffsetsResponsePartition(
                        part.partition_index,
                        int_to_bytes(Errors.UNKNOWN_TOPIC_OR_PARTITION, 2),
                        int_to_bytes_signed(-1, 8),
                        int_to_bytes_signed(-1, 8),
                        int_to_bytes(0, 4),
                    )
                )
                continue

            timestamp_req = bytes_to_int_signed(part.timestamp)
            log_path = (
                f"{partition_log_dir}/{topic_name.decode()}-{partition_id}"
                "/00000000000000000000.log"
            )

            if timestamp_req == -2:  # earliest
                offset = 0
            elif timestamp_req == -1:  # latest
                offset = log_end_offset(log_path)
            else:
                # Timestamp-based lookup — return earliest for simplicity
                offset = 0

            logger.debug(
                "ListOffsets: topic={} partition={} timestamp={} -> offset={}",
                topic_name, partition_id, timestamp_req, offset,
            )
            partition_responses.append(
                ListOffsetsResponsePartition(
                    part.partition_index,
                    int_to_bytes(Errors.NO_ERROR, 2),
                    int_to_bytes_signed(-1, 8),  # timestamp: -1 (not available)
                    int_to_bytes(offset, 8),
                    int_to_bytes(0, 4),           # leader_epoch: 0
                )
            )
        response_topics.append(ListOffsetsResponseTopic(topic_name, partition_responses))

    return ListOffsetsResponse(
        ResponseHeaderV0(correlation_id),
        ListOffsetsResponseBody(
            int_to_bytes(0, WireProtocol.TIME_BYTES),
            response_topics,
            api_version,
        ),
    )
