from dataclasses import dataclass
from typing import Any, Optional

from app.messages import ApiRequest, ApiResponse
from app.messages.headers import ResponseHeaderV1
from app.protocol import WireProtocol, bytes_to_int, int_to_bytes, int_to_bytes_signed


class DescribeTopicPartitionsRequest(ApiRequest):
    
    def get_header(self):
        return self.get_header_v2()
    
    def get_body(self):
        topic_array_raw_size = self.buffer.read_bytes(WireProtocol.LENGTH_BYTES) # Length of the topic array + 1
        topic_array_size = bytes_to_int(topic_array_raw_size) - 1
        topics = []
        for _ in range(topic_array_size):
            topic_name_raw_len = self.buffer.read_bytes(WireProtocol.LENGTH_BYTES) # Length of the name + 1
            topic_name_len = bytes_to_int(topic_name_raw_len) - 1
            topic_name = self.buffer.read_bytes(topic_name_len)
            topic_tag_buffer = self.buffer.read_bytes(WireProtocol.TAG_BUFFER_BYTES)
            topics.append(Topic(topic_name, topic_name, topic_tag_buffer))
        response_part_limit_raw = self.buffer.read_bytes(WireProtocol.RESPONSE_PARTITION_LIMIT_BYTES)
        cursor_raw = self.buffer.read_bytes(WireProtocol.CURSOR_BYTES)
        tag_buffer_raw = self.buffer.read_bytes(WireProtocol.TAG_BUFFER_BYTES)
        return DescribeTopicPartitionRequestBody(
            topics, response_part_limit_raw, cursor_raw, tag_buffer_raw
        )
        
            
class TopicRequest:
    def __init__(
        self,
        name_length: bytes,
        topic_name: bytes,
        tag_buffer: bytes
    ):
        self.name_length = name_length
        self.topic_name = topic_name
        self.tag_buffer = tag_buffer
        
    def get_bytes(self):
        return self.name_length + self.topic_name + self.tag_buffer
    
    
class DescribeTopicPartitionRequestBody:
    def __init__(
        self,
        topics_array: list[TopicRequest],
        resp_part_limit: bytes,
        cursor: bytes,
        tag_buffer: bytes
    ):
        self.topic_array = topics_array
        self.resp_part_limit = resp_part_limit
        self.cursor = cursor
        self.tag_buffer = tag_buffer
        
    def get_bytes(self):
        result = int_to_bytes(
            len(self.topic_array) + 1, WireProtocol.LENGTH_BYTES
        )
        for topic in self.topic_array:
            result += topic.get_bytes()
        result +=  self.resp_part_limit + self.cursor + self.tag_buffer
        return result


@dataclass
class TopicName:
    length: bytes
    content: bytes
    
    def get_bytes(self):
        return b"".join([self.length, self.content])
    

@dataclass
class Topic:
    error: bytes
    topic_name: TopicName
    topic_id: bytes
    is_internal: bytes
    partitions_array: list[bytes] # TODO Should be a generic way for the partition list
    topic_auth_operations: bytes
    tag_buffer: bytes
    
    def get_bytes(self):
        result = (self.error + self.topic_name.get_bytes() + 
                    self.topic_id + self.is_internal + 
                    int_to_bytes(len(self.partitions_array) + 1, WireProtocol.LENGTH_BYTES) +
                    # No real patrition array content for now
                    self.topic_auth_operations + self.tag_buffer
                    )            
        return result


class DescribeTopicPartitionResponseBody:
    def __init__(
        self,
        throttle_time: bytes,
        topics_array: list[Topic],
        next_cursor: Optional[bytes],
        tag_buffer: bytes
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
        if not self.next_cursor:
            result += int_to_bytes_signed(-1, WireProtocol.CURSOR_BYTES)
        else:
            result += int_to_bytes_signed(1, WireProtocol.CURSOR_BYTES) + self.next_cursor
        result += self.tag_buffer
        return result


class DescribeTopicPartitionsResponse(ApiResponse):
    def __init__(self, header: ResponseHeaderV1, body: DescribeTopicPartitionResponseBody):
        self.header = header
        self.body = body
