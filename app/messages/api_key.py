from dataclasses import dataclass

from app.protocol import int_to_bytes, WireProtocol


class ApiKeyConstants:
    PRODUCE = 0
    FETCH = 1
    LIST_OFFSETS = 2
    METADATA = 3
    API_VERSION = 18
    INIT_PRODUCER_ID = 22
    DESCRIBE_TOPIC_PARTITION = 75


@dataclass
class ApiKey:
    api_key: bytes
    min_version: bytes
    max_version: bytes
    tag_buffer: bytes

    def get_bytes(self) -> bytes:
        return self.api_key + self.min_version + self.max_version + self.tag_buffer


api_version_key = ApiKey(
    int_to_bytes(ApiKeyConstants.API_VERSION, WireProtocol.REQUEST_API_KEY_BYTES),
    int_to_bytes(0, WireProtocol.REQUEST_API_VERSION_BYTES),
    int_to_bytes(4, WireProtocol.REQUEST_API_VERSION_BYTES),
    int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
)

describe_topic_partiition_key = ApiKey(
    int_to_bytes(
        ApiKeyConstants.DESCRIBE_TOPIC_PARTITION, WireProtocol.REQUEST_API_KEY_BYTES
    ),
    int_to_bytes(0, WireProtocol.REQUEST_API_VERSION_BYTES),
    int_to_bytes(4, WireProtocol.REQUEST_API_VERSION_BYTES),
    int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
)

fetch_key = ApiKey(
    int_to_bytes(ApiKeyConstants.FETCH, WireProtocol.REQUEST_API_KEY_BYTES),
    int_to_bytes(0, WireProtocol.REQUEST_API_VERSION_BYTES),
    int_to_bytes(16, WireProtocol.REQUEST_API_VERSION_BYTES),
    int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
)

produce_key = ApiKey(
    int_to_bytes(ApiKeyConstants.PRODUCE, WireProtocol.REQUEST_API_KEY_BYTES),
    int_to_bytes(0, WireProtocol.REQUEST_API_VERSION_BYTES),
    int_to_bytes(11, WireProtocol.REQUEST_API_VERSION_BYTES),
    int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
)

metadata_key = ApiKey(
    int_to_bytes(ApiKeyConstants.METADATA, WireProtocol.REQUEST_API_KEY_BYTES),
    int_to_bytes(0, WireProtocol.REQUEST_API_VERSION_BYTES),
    int_to_bytes(5, WireProtocol.REQUEST_API_VERSION_BYTES),
    int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
)

init_producer_id_key = ApiKey(
    int_to_bytes(ApiKeyConstants.INIT_PRODUCER_ID, WireProtocol.REQUEST_API_KEY_BYTES),
    int_to_bytes(0, WireProtocol.REQUEST_API_VERSION_BYTES),
    int_to_bytes(4, WireProtocol.REQUEST_API_VERSION_BYTES),
    int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
)

list_offsets_key = ApiKey(
    int_to_bytes(ApiKeyConstants.LIST_OFFSETS, WireProtocol.REQUEST_API_KEY_BYTES),
    int_to_bytes(1, WireProtocol.REQUEST_API_VERSION_BYTES),
    int_to_bytes(5, WireProtocol.REQUEST_API_VERSION_BYTES),
    int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
)
