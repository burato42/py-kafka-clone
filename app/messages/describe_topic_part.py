from dataclasses import dataclass
from typing import Optional

from app.messages import ApiRequest, ApiResponse
from app.messages.headers import ResponseHeaderV1
from app.protocol import WireProtocol, bytes_to_int, int_to_bytes


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
class Topic:
    error: bytes
    topic_name: TopicName
    topic_id: bytes
    is_internal: bytes
    partitions_array: list[bytes]  # TODO Should be a generic way for the partition list
    topic_auth_operations: bytes
    tag_buffer: bytes

    def get_bytes(self):
        result = (
            self.error
            + self.topic_name.get_bytes()
            + self.topic_id
            + self.is_internal
            + int_to_bytes(len(self.partitions_array) + 1, WireProtocol.LENGTH_BYTES)
            +
            # No real patrition array content for now
            self.topic_auth_operations
            + self.tag_buffer
        )
        return result


@dataclass
class DescribeTopicPartitionResponseBody:
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
class DescribeTopicPartitionsResponse(ApiResponse):
    header: ResponseHeaderV1
    body: DescribeTopicPartitionResponseBody
