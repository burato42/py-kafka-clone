from dataclasses import dataclass
from typing import Optional

from loguru import logger

from app.messages import ApiRequest, ApiResponse
from app.messages.cluster_metadata_log import (
    ClusterMetadataLogFile,
    PartitionRecordValue,
    TopicRecordValue,
)
from app.messages.headers import RequestHeader, ResponseHeaderV0, ResponseHeaderV1
from app.protocol import Errors, WireProtocol, bytes_to_int, bytes_to_int_signed, int_to_bytes
from app.tools import encode_uvarint, log_end_offset, read_compact_nullable_string, read_compact_string, read_log_from_offset


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
    # For v13+: topic_id is a 16-byte UUID, topic_name is None
    # For v0-v12: topic_name is bytes, topic_id is None
    topic_id: Optional[bytes]
    topic_name: Optional[bytes]
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
    header: RequestHeader
    body: FetchRequestBody

    def get_header(self) -> RequestHeader:
        api_version = bytes_to_int(self.buffer.data[2:4])
        if api_version >= 12:
            return self.read_header_flexible()
        return self.read_header()

    def get_body(self) -> FetchRequestBody:
        api_version = bytes_to_int(self.header.api_version)
        if api_version >= 12:
            return self._get_body_flexible(api_version)
        return self._get_body_legacy(api_version)

    def _get_body_flexible(self, api_version: int) -> FetchRequestBody:
        """Fetch v12+ — flexible encoding, topic UUIDs (v13+) or names (v12).
        replica_id moved to tagged fields in v12+."""
        max_wait_ms = self.buffer.read_bytes(4)
        min_bytes = self.buffer.read_bytes(4)
        max_bytes = self.buffer.read_bytes(4)
        isolation_level = self.buffer.read_bytes(1)
        session_id = self.buffer.read_bytes(4)
        session_epoch = self.buffer.read_bytes(4)

        topics_count = bytes_to_int(self.buffer.read_bytes(1)) - 1
        topics = []
        for _ in range(topics_count):
            if api_version >= 13:
                topic_id = self.buffer.read_bytes(16)
                topic_name = None
            else:
                topic_name = read_compact_string(self.buffer)
                topic_id = None
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
                partitions.append(
                    FetchPartition(
                        partition, current_leader_epoch, fetch_offset,
                        last_fetched_epoch, log_start_offset, partition_max_bytes,
                    )
                )
            self.buffer.read_bytes(1)  # topic tag buffer
            topics.append(FetchTopic(topic_id, topic_name, partitions))

        forgotten_count = bytes_to_int(self.buffer.read_bytes(1)) - 1
        for _ in range(forgotten_count):
            self.buffer.read_bytes(16)  # topic_id
            fp_count = bytes_to_int(self.buffer.read_bytes(1)) - 1
            for _ in range(fp_count):
                self.buffer.read_bytes(4)
            self.buffer.read_bytes(1)

        rack_id = read_compact_string(self.buffer)

        cluster_id: Optional[bytes] = None
        replica_id_tagged: Optional[bytes] = None
        replica_epoch: Optional[bytes] = None
        num_tagged_fields = bytes_to_int(self.buffer.read_bytes(1))
        for _ in range(num_tagged_fields):
            tag = bytes_to_int(self.buffer.read_bytes(1))
            size = bytes_to_int(self.buffer.read_bytes(1))
            if tag == 0:
                cluster_id = read_compact_nullable_string(self.buffer)
            elif tag == 1:
                replica_id_tagged = self.buffer.read_bytes(4)
                replica_epoch = self.buffer.read_bytes(8)
            else:
                self.buffer.read_bytes(size)

        return FetchRequestBody(
            max_wait_ms, min_bytes, max_bytes, isolation_level,
            session_id, session_epoch, topics, [], rack_id,
            cluster_id, replica_id_tagged, replica_epoch,
        )

    def _get_body_legacy(self, api_version: int) -> FetchRequestBody:
        """Fetch v0-v11 — non-flexible, 4-byte array counts, topic names."""
        replica_id = self.buffer.read_bytes(4)
        max_wait_ms = self.buffer.read_bytes(4)
        min_bytes = self.buffer.read_bytes(4)
        max_bytes = self.buffer.read_bytes(4) if api_version >= 3 else b"\x07\xff\xff\xff"
        isolation_level = self.buffer.read_bytes(1) if api_version >= 4 else b"\x00"
        session_id = self.buffer.read_bytes(4) if api_version >= 7 else b"\x00\x00\x00\x00"
        session_epoch = self.buffer.read_bytes(4) if api_version >= 7 else b"\xff\xff\xff\xff"

        topics_count = bytes_to_int(self.buffer.read_bytes(4))
        topics = []
        for _ in range(topics_count):
            name_len = bytes_to_int(self.buffer.read_bytes(2))
            topic_name = self.buffer.read_bytes(name_len)
            partitions_count = bytes_to_int(self.buffer.read_bytes(4))
            partitions = []
            for _ in range(partitions_count):
                partition = self.buffer.read_bytes(4)
                current_leader_epoch = (
                    self.buffer.read_bytes(4) if api_version >= 9 else b"\xff\xff\xff\xff"
                )
                fetch_offset = self.buffer.read_bytes(8)
                last_fetched_epoch = (
                    self.buffer.read_bytes(4) if api_version >= 12 else b"\xff\xff\xff\xff"
                )
                log_start_offset = (
                    self.buffer.read_bytes(8) if api_version >= 5 else b"\xff\xff\xff\xff\xff\xff\xff\xff"
                )
                partition_max_bytes = self.buffer.read_bytes(4)
                partitions.append(
                    FetchPartition(
                        partition, current_leader_epoch, fetch_offset,
                        last_fetched_epoch, log_start_offset, partition_max_bytes,
                    )
                )
            topics.append(FetchTopic(None, topic_name, partitions))

        forgotten_count = bytes_to_int(self.buffer.read_bytes(4)) if api_version >= 7 else 0
        for _ in range(forgotten_count):
            name_len = bytes_to_int(self.buffer.read_bytes(2))
            self.buffer.read_bytes(name_len)
            fp_count = bytes_to_int(self.buffer.read_bytes(4))
            for _ in range(fp_count):
                self.buffer.read_bytes(4)

        rack_id = b""
        if api_version >= 11:
            rack_len = bytes_to_int(self.buffer.read_bytes(2))
            rack_id = self.buffer.read_bytes(rack_len) if rack_len > 0 else b""

        return FetchRequestBody(
            max_wait_ms, min_bytes, max_bytes, isolation_level,
            session_id, session_epoch, topics, [], rack_id,
            None, None, None,
        )


@dataclass
class FetchResponsePartition:
    partition_index: bytes  # INT32
    error_code: bytes  # INT16
    high_watermark: bytes  # INT64
    last_stable_offset: bytes  # INT64
    log_start_offset: bytes  # INT64
    aborted_transactions: bytes  # compact array (empty = \x01)
    preferred_read_replica: bytes  # INT32
    records: bytes  # compact nullable bytes (null = \x00)
    tag_buffer: bytes

    def get_bytes(self) -> bytes:
        if self.records == b"\x00":
            records_bytes = b"\x00"
        else:
            n = len(self.records)
            records_bytes = encode_uvarint(n + 1) + self.records
        return (
            self.partition_index
            + self.error_code
            + self.high_watermark
            + self.last_stable_offset
            + self.log_start_offset
            + b"\x01"  # aborted_transactions: empty compact array
            + int_to_bytes(0xFFFFFFFF, 4)  # preferred_read_replica: -1
            + records_bytes
            + b"\x00"  # tag_buffer
        )

    def get_bytes_legacy(self, api_version: int = 10) -> bytes:
        """For v0-v11: no compact encoding, no tag buffer."""
        if self.records == b"\x00":
            records_bytes = int_to_bytes(0, 4)  # empty records (length=0)
        else:
            records_bytes = int_to_bytes(len(self.records), 4) + self.records
        result = self.partition_index + self.error_code + self.high_watermark
        if api_version >= 5:
            result += self.last_stable_offset
        if api_version >= 5:
            result += self.log_start_offset
        if api_version >= 4:
            result += int_to_bytes(0xFFFFFFFF, 4)  # aborted_transactions: null array (-1)
        if api_version >= 11:
            result += int_to_bytes(0xFFFFFFFF, 4)  # preferred_read_replica: -1
        result += records_bytes
        return result


@dataclass
class FetchResponseTopic:
    topic_id: Optional[bytes]    # for v13+
    topic_name: Optional[bytes]  # for v0-v12
    partitions: list[FetchResponsePartition]

    def get_bytes(self, api_version: int) -> bytes:
        if api_version >= 13:
            result = self.topic_id + int_to_bytes(len(self.partitions) + 1, 1)
            for part in self.partitions:
                result += part.get_bytes()
            result += b"\x00"
        elif api_version >= 12:
            name = self.topic_name or b""
            result = encode_uvarint(len(name) + 1) + name
            result += int_to_bytes(len(self.partitions) + 1, 1)
            for part in self.partitions:
                result += part.get_bytes()
            result += b"\x00"
        else:
            name = self.topic_name or b""
            result = int_to_bytes(len(name), 2) + name
            result += int_to_bytes(len(self.partitions), 4)
            for part in self.partitions:
                result += part.get_bytes_legacy(api_version)
        return result


@dataclass
class FetchResponseBody:
    throttle_time: bytes
    error_code: bytes
    session_id: bytes
    responses: list[FetchResponseTopic]
    tag_buffer: bytes
    api_version: int = 16

    def get_bytes(self) -> bytes:
        if self.api_version >= 12:
            result = (
                self.throttle_time
                + self.error_code
                + self.session_id
                + int_to_bytes(len(self.responses) + 1, WireProtocol.LENGTH_BYTES)
            )
            for response in self.responses:
                result += response.get_bytes(self.api_version)
            result += self.tag_buffer
        else:
            result = self.throttle_time
            if self.api_version >= 7:
                result += self.error_code + self.session_id
            result += int_to_bytes(len(self.responses), 4)
            for response in self.responses:
                result += response.get_bytes(self.api_version)
        return result


@dataclass
class FetchResponse(ApiResponse):
    header: ResponseHeaderV0 | ResponseHeaderV1
    body: FetchResponseBody

    def get_bytes(self) -> bytes:
        return self.header.get_bytes() + self.body.get_bytes()


def handle_fetch_request(
    request: FetchRequest,
    cluster_metadata: ClusterMetadataLogFile,
    partition_log_dir: str,
) -> ApiResponse:
    api_version = bytes_to_int(request.header.api_version)

    # Build lookup maps from cluster metadata
    existing_topics_by_uuid: dict[bytes, bytes] = {}   # uuid -> name
    existing_topics_by_name: dict[bytes, bytes] = {}   # name -> uuid
    valid_partitions: set[tuple[bytes, int]] = set()   # (name, partition_id)

    for record_batch in cluster_metadata.record_batches:
        for record in record_batch.records:
            val = record.value
            if isinstance(val, TopicRecordValue):
                uuid = bytes(val.topic_uuid)
                name = bytes(val.topic_name)
                existing_topics_by_uuid[uuid] = name
                existing_topics_by_name[name] = uuid
            elif isinstance(val, PartitionRecordValue):
                topic_name = existing_topics_by_uuid.get(bytes(val.topic_uuid))
                if topic_name is not None:
                    valid_partitions.add((topic_name, bytes_to_int(val.partition_id)))

    correlation_id = request.header.correlation_id
    responses = []

    for tpc in request.body.topics:
        # Resolve topic name regardless of whether request used UUID or name
        if tpc.topic_id is not None:
            topic_name = existing_topics_by_uuid.get(bytes(tpc.topic_id))
            topic_id = bytes(tpc.topic_id)
        else:
            topic_name = bytes(tpc.topic_name) if tpc.topic_name else None
            topic_id = existing_topics_by_name.get(topic_name) if topic_name else None

        if topic_name is None:
            error_partition = FetchResponsePartition(
                int_to_bytes(0, 4),
                int_to_bytes(Errors.UNKNOWN_TOPIC_ID if tpc.topic_id else Errors.UNKNOWN_TOPIC_OR_PARTITION, 2),
                int_to_bytes(0, 8), int_to_bytes(0, 8), int_to_bytes(0, 8),
                b"\x01", int_to_bytes(0xFFFFFFFF, 4), b"\x00", b"\x00",
            )
            responses.append(FetchResponseTopic(
                tpc.topic_id, tpc.topic_name, [error_partition]
            ))
            continue

        partitions = []
        for fetch_partition in tpc.partitions:
            partition_idx = bytes_to_int(fetch_partition.partition)
            logger.debug("Found partition: {}, topic is {}", partition_idx, topic_name)
            log_path = f"{partition_log_dir}/{topic_name.decode()}-{partition_idx}/00000000000000000000.log"
            fetch_off = bytes_to_int(fetch_partition.fetch_offset)
            leo = log_end_offset(log_path)
            log_data = read_log_from_offset(log_path, fetch_off)
            logger.debug(
                "Fetch topic={} partition={} fetch_offset={} leo={} data_bytes={}",
                topic_name, partition_idx, fetch_off, leo, len(log_data),
            )
            partitions.append(
                FetchResponsePartition(
                    fetch_partition.partition,
                    int_to_bytes(Errors.NO_ERROR, 2),
                    int_to_bytes(leo, 8),
                    int_to_bytes(leo, 8),
                    int_to_bytes(0, 8),
                    b"\x01",
                    int_to_bytes(0xFFFFFFFF, 4),
                    log_data if log_data else b"\x00",
                    b"\x00",
                )
            )
        responses.append(FetchResponseTopic(topic_id, topic_name, partitions))

    if api_version >= 12:
        header = ResponseHeaderV1(
            correlation_id, int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES)
        )
    else:
        header = ResponseHeaderV0(correlation_id)

    return FetchResponse(
        header,
        FetchResponseBody(
            int_to_bytes(0, WireProtocol.TIME_BYTES),
            int_to_bytes(Errors.NO_ERROR, WireProtocol.ERROR_BYTES),
            int_to_bytes(0, 4),
            responses,
            int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
            api_version=api_version,
        ),
    )
