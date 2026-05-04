from dataclasses import dataclass
from typing import Optional

from loguru import logger

from app.connection import Buffer
from app.messages import ApiRequest, ApiResponse
from app.messages.cluster_metadata_log import (
    read_cluster_metadata_log,
    TopicRecordValue,
    PartitionRecordValue,
)
from app.messages.headers import ResponseHeaderV1
from app.protocol import (
    Errors,
    WireProtocol,
    bytes_to_int,
    int_to_bytes,
    int_to_bytes_signed,
)


class DescribeTopicPartitionsRequest(ApiRequest):
    def get_header(self):
        return self.get_header_v2()

    def get_body(self):
        # TODO Implement logic for compact arrays
        topic_array_raw_size = self.buffer.read_bytes(
            WireProtocol.LENGTH_BYTES
        )  # Length of the topic array + 1
        topic_array_size = bytes_to_int(topic_array_raw_size) - 1
        topics = []
        for _ in range(topic_array_size):
            topic_name_raw_len = self.buffer.read_bytes(WireProtocol.LENGTH_BYTES)
            topic_name_len = bytes_to_int(topic_name_raw_len)
            topic_name = self.buffer.read_bytes(topic_name_len - 1)
            topic_tag_buffer = self.buffer.read_bytes(WireProtocol.TAG_BUFFER_BYTES)
            topics.append(TopicRequest(topic_name, topic_tag_buffer))
        response_part_limit_raw = self.buffer.read_bytes(
            WireProtocol.RESPONSE_PARTITION_LIMIT_BYTES
        )
        cursor_raw = self.buffer.read_bytes(WireProtocol.CURSOR_BYTES)
        tag_buffer_raw = self.buffer.read_bytes(WireProtocol.TAG_BUFFER_BYTES)
        return DescribeTopicPartitionRequestBody(
            topics, response_part_limit_raw, cursor_raw, tag_buffer_raw
        )


@dataclass
class TopicRequest:
    topic_name: bytes
    tag_buffer: bytes


@dataclass
class DescribeTopicPartitionRequestBody:
    topics_array: list[TopicRequest]
    resp_part_limit: bytes
    cursor: bytes
    tag_buffer: bytes


@dataclass
class TopicName:
    content: bytes

    def get_bytes(self):
        size = len(self.content)
        return b"".join(
            [int_to_bytes(size + 1, WireProtocol.LENGTH_BYTES), self.content]
        )


@dataclass
class Partition:
    error_code: bytes
    partition_id: bytes
    leader_id: bytes
    leader_epoch: bytes
    replicas_array: list[bytes]
    in_sync_replicas_array: list[bytes]
    eligible_leader_replicas_array: list[bytes]
    last_known_elr_array: list[bytes]
    offline_replicas_array: list[bytes]
    tag_buffer: bytes

    def get_bytes(self):
        result = (
            self.error_code
            + self.partition_id
            + self.leader_id
            + self.leader_epoch
            + int_to_bytes(len(self.replicas_array) + 1, WireProtocol.LENGTH_BYTES)
            + b"".join(replica for replica in self.replicas_array)
            + int_to_bytes(
                len(self.in_sync_replicas_array) + 1, WireProtocol.LENGTH_BYTES
            )
            + b"".join(replica for replica in self.in_sync_replicas_array)
            + int_to_bytes(
                len(self.eligible_leader_replicas_array) + 1,
                WireProtocol.LENGTH_BYTES,
            )
            + b"".join(replica for replica in self.eligible_leader_replicas_array)
            + int_to_bytes(
                len(self.last_known_elr_array) + 1, WireProtocol.LENGTH_BYTES
            )
            + b"".join(replica for replica in self.last_known_elr_array)
            + int_to_bytes(
                len(self.offline_replicas_array) + 1, WireProtocol.LENGTH_BYTES
            )
            + b"".join(replica for replica in self.offline_replicas_array)
            + self.tag_buffer
        )
        return result


@dataclass
class Topic:
    error: bytes
    topic_name: TopicName
    topic_id: bytes
    is_internal: bytes
    partitions_array: list[Partition]
    topic_auth_operations: bytes
    tag_buffer: bytes

    def get_bytes(self):
        result = (
            self.error
            + self.topic_name.get_bytes()
            + self.topic_id
            + self.is_internal
            + int_to_bytes(len(self.partitions_array) + 1, WireProtocol.LENGTH_BYTES)
            + b"".join(partition.get_bytes() for partition in self.partitions_array)
            + self.topic_auth_operations
            + self.tag_buffer
        )
        return result


@dataclass
class DescribeTopicPartitionResponseBody:
    # TODO init is not needed as it's a dataclass
    def __init__(
        self,
        throttle_time: bytes,
        topics_array: list[Topic],
        next_cursor: Optional[bytes],
        tag_buffer: bytes,
    ):
        self.throttle_time = throttle_time
        self.topics_array = topics_array
        self.next_cursor = next_cursor
        self.tag_buffer = tag_buffer

    def get_bytes(self):
        result = self.throttle_time + int_to_bytes(
            len(self.topics_array) + 1, WireProtocol.LENGTH_BYTES
        )
        for topic in self.topics_array:
            result += topic.get_bytes()
        result += self.next_cursor + self.tag_buffer
        return result


@dataclass
class DescribeTopicPartitionsResponseV0(ApiResponse):
    header: ResponseHeaderV1
    body: DescribeTopicPartitionResponseBody


def handle_describe_topic_partition_request(
    request: DescribeTopicPartitionsRequest,
    configuration: dict[str, bytes],
) -> ApiResponse:
    try:
        with open(configuration["cluster_metadata_file"], "rb") as metadata_file:
            cluster_metadata = metadata_file.read()
            metadata_buffer = Buffer(len(cluster_metadata), cluster_metadata)
            metadata_log = read_cluster_metadata_log(metadata_buffer)
            logger.debug(metadata_log)

    except (FileNotFoundError, FileExistsError) as e:
        logger.error("Cannot find or read cluster metadata: {}", e)
    except Exception as e:
        logger.error("There is an error during getting cluster metadata: {}", e)

    requested_topics = {bytes(topic.topic_name) for topic in request.body.topics_array}

    topics: dict[bytes, Topic] = {}

    for record_batch in metadata_log.record_batches:
        for record in record_batch.records:
            val = record.value

            if isinstance(val, TopicRecordValue):
                if (
                    bytes(val.topic_name) in requested_topics
                    and val.topic_uuid not in topics
                ):
                    logger.info(
                        "Found topic {} in cluster metadata log", val.topic_name
                    )
                    topics[val.topic_uuid] = Topic(
                        int_to_bytes(Errors.NO_ERROR, WireProtocol.ERROR_BYTES),
                        TopicName(val.topic_name),
                        val.topic_uuid,
                        int_to_bytes(0, WireProtocol.BOOLEAN_BYTES),
                        [],
                        int_to_bytes(0, WireProtocol.TOPIC_AUTH_OPS_BYTES),
                        int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
                    )
            elif isinstance(val, PartitionRecordValue):
                if val.topic_uuid in topics:
                    partition = Partition(
                        int_to_bytes(Errors.NO_ERROR, WireProtocol.ERROR_BYTES),
                        val.partition_id,
                        val.leader,
                        val.leader_epoch,
                        val.replica_array,
                        val.in_sync_replica_array,
                        val.removing_replicas_array,
                        val.adding_replicas_array,
                        [],
                        int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
                    )
                    logger.debug(
                        "Partition found for topic uuid {}: {}",
                        val.topic_uuid,
                        partition,
                    )
                    topics[val.topic_uuid].partitions_array.append(partition)

    topic_content = list(
        sorted(
            topics.values(), key=lambda topic: topic.topic_name.content.decode("utf-8")
        )
    )

    found_names = {bytes(t.topic_name.content) for t in topics.values()}
    for name in requested_topics:
        if name not in found_names:
            logger.warning("Topic {} not found in cluster metadata log", name)
            topic_content.append(
                Topic(
                    int_to_bytes(
                        Errors.UNKNOWN_TOPIC_OR_PARTITION, WireProtocol.ERROR_BYTES
                    ),
                    TopicName(name),
                    int_to_bytes(0, WireProtocol.TOPIC_ID_BYTES),
                    int_to_bytes(0, WireProtocol.BOOLEAN_BYTES),
                    [],
                    int_to_bytes(0, WireProtocol.TOPIC_AUTH_OPS_BYTES),
                    int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
                )
            )

    payload = DescribeTopicPartitionsResponseV0(
        ResponseHeaderV1(
            request.header.correlation_id,
            int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
        ),
        DescribeTopicPartitionResponseBody(
            int_to_bytes(0, WireProtocol.TIME_BYTES),
            topic_content,
            int_to_bytes_signed(-1, WireProtocol.CURSOR_BYTES),
            int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
        ),
    )
    return payload
