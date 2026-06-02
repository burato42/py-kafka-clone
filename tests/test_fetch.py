from unittest.mock import patch

from app.messages.cluster_metadata_log import (
    ClusterMetadataLogFile,
    RecordBatch,
    Record,
    TopicRecordValue,
)
from app.messages.fetch import (
    FetchRequest,
    FetchResponsePartition,
    FetchResponseTopic,
    handle_fetch_request,
)
from app.protocol import Errors, WireProtocol, bytes_to_int, int_to_bytes
from app.tools import encode_uvarint
from tests.conftest import make_buffer


TOPIC_UUID = bytes(range(16))  # deterministic 16-byte UUID
UNKNOWN_UUID = bytes(reversed(range(16)))


def build_fetch_request_bytes(
    api_version: int = 16,
    correlation_id: int = 1,
    client_id: bytes = b"test",
    topics: list[tuple[bytes, list[int]]] | None = None,  # [(topic_uuid, [partitions])]
    cluster_id: bytes | None = None,
) -> bytes:
    """Build a minimal FetchRequest v16 byte payload."""
    header = (
        int_to_bytes(1, WireProtocol.REQUEST_API_KEY_BYTES)  # api_key=1 (Fetch)
        + int_to_bytes(api_version, WireProtocol.REQUEST_API_VERSION_BYTES)
        + int_to_bytes(correlation_id, WireProtocol.CORRRELATION_ID_BYTES)
        + int_to_bytes(len(client_id), WireProtocol.CLIENT_ID_BYTES)
        + client_id
        + b"\x00"  # tag_buffer
    )

    body = (
        int_to_bytes(500, 4)   # max_wait_ms
        + int_to_bytes(0, 4)   # min_bytes
        + int_to_bytes(0x7FFFFFFF, 4)  # max_bytes
        + int_to_bytes(0, 1)   # isolation_level
        + int_to_bytes(0, 4)   # session_id
        + int_to_bytes(-1 & 0xFFFFFFFF, 4)  # session_epoch = -1
    )

    if topics is None:
        topics = []

    # compact array: length = count+1
    body += bytes([len(topics) + 1])
    for topic_uuid, partitions in topics:
        body += topic_uuid
        body += bytes([len(partitions) + 1])  # partitions compact array
        for partition_idx in partitions:
            body += (
                int_to_bytes(partition_idx, 4)   # partition
                + int_to_bytes(0, 4)             # current_leader_epoch
                + int_to_bytes(0, 8)             # fetch_offset
                + int_to_bytes(0, 4)             # last_fetched_epoch
                + int_to_bytes(0, 8)             # log_start_offset
                + int_to_bytes(0x7FFFFFFF, 4)    # partition_max_bytes
                + b"\x00"                        # partition tag_buffer
            )
        body += b"\x00"  # topic tag_buffer

    body += b"\x01"  # forgotten_topics_data: empty compact array
    body += b"\x01"  # rack_id: empty compact string (length = 1 means 0 chars)

    # Tagged fields
    if cluster_id is not None:
        # tag=0, size = uvarint-encoded length of cluster_id compact string
        cluster_id_encoded = bytes([len(cluster_id) + 1]) + cluster_id
        body += bytes([1])  # num_tagged_fields = 1
        body += bytes([0])  # tag = 0
        body += bytes([len(cluster_id_encoded)])  # size
        body += cluster_id_encoded
    else:
        body += b"\x00"  # num_tagged_fields = 0

    return header + body


def make_cluster_metadata(topic_uuid: bytes, topic_name: bytes) -> ClusterMetadataLogFile:
    """Build a minimal ClusterMetadataLogFile with one TopicRecordValue."""
    record_value = TopicRecordValue(
        frame_version=b"\x01",
        type=b"\x02",
        version=b"\x00",
        topic_name=topic_name,
        topic_uuid=topic_uuid,
        tagged_fields_count=b"\x00",
    )
    record = Record(
        length=0,
        attributes=b"\x00",
        timestamp_delta=0,
        offset_delta=0,
        key=b"",
        value=record_value,
        headers_array_count=b"\x00",
    )
    batch = RecordBatch(
        base_offset=int_to_bytes(0, 8),
        batch_length=int_to_bytes(0, 4),
        partition_leader_epoch=int_to_bytes(0, 4),
        magic_byte=b"\x02",
        crc=int_to_bytes(0, 4),
        attributes=int_to_bytes(0, 2),
        last_offset_delta=int_to_bytes(0, 4),
        base_timestamp=int_to_bytes(0, 8),
        max_timestamp=int_to_bytes(0, 8),
        producer_id=int_to_bytes(0, 8),
        producer_epoch=int_to_bytes(0, 2),
        base_sequence=int_to_bytes(0, 4),
        records=[record],
    )
    return ClusterMetadataLogFile(record_batches=[batch])


class TestFetchRequestParsing:
    def test_header_api_key(self):
        raw = build_fetch_request_bytes()
        req = FetchRequest(make_buffer(raw))
        assert bytes_to_int(req.header.api_key) == 1

    def test_header_api_version(self):
        raw = build_fetch_request_bytes(api_version=16)
        req = FetchRequest(make_buffer(raw))
        assert bytes_to_int(req.header.api_version) == 16

    def test_header_correlation_id(self):
        raw = build_fetch_request_bytes(correlation_id=42)
        req = FetchRequest(make_buffer(raw))
        assert bytes_to_int(req.header.correlation_id) == 42

    def test_body_no_topics(self):
        raw = build_fetch_request_bytes(topics=[])
        req = FetchRequest(make_buffer(raw))
        assert req.body.topics == []

    def test_body_single_topic_parsed(self):
        raw = build_fetch_request_bytes(topics=[(TOPIC_UUID, [0])])
        req = FetchRequest(make_buffer(raw))
        assert len(req.body.topics) == 1
        assert bytes(req.body.topics[0].topic_id) == TOPIC_UUID

    def test_body_single_topic_single_partition(self):
        raw = build_fetch_request_bytes(topics=[(TOPIC_UUID, [0])])
        req = FetchRequest(make_buffer(raw))
        partitions = req.body.topics[0].partitions
        assert len(partitions) == 1
        assert bytes_to_int(partitions[0].partition) == 0

    def test_body_single_topic_multiple_partitions(self):
        raw = build_fetch_request_bytes(topics=[(TOPIC_UUID, [0, 1, 2])])
        req = FetchRequest(make_buffer(raw))
        partitions = req.body.topics[0].partitions
        assert len(partitions) == 3
        assert [bytes_to_int(p.partition) for p in partitions] == [0, 1, 2]

    def test_body_multiple_topics(self):
        uuid2 = bytes(range(16, 32))
        raw = build_fetch_request_bytes(topics=[(TOPIC_UUID, [0]), (uuid2, [1])])
        req = FetchRequest(make_buffer(raw))
        assert len(req.body.topics) == 2

    def test_body_no_forgotten_topics(self):
        raw = build_fetch_request_bytes(topics=[])
        req = FetchRequest(make_buffer(raw))
        assert req.body.forgotten_topics_data == []

    def test_tagged_field_cluster_id(self):
        raw = build_fetch_request_bytes(cluster_id=b"my-cluster")
        req = FetchRequest(make_buffer(raw))
        assert req.body.cluster_id == b"my-cluster"

    def test_tagged_field_cluster_id_absent(self):
        raw = build_fetch_request_bytes(cluster_id=None)
        req = FetchRequest(make_buffer(raw))
        assert req.body.cluster_id is None


class TestFetchResponsePartitionGetBytes:
    def _make_partition(self, records: bytes) -> FetchResponsePartition:
        return FetchResponsePartition(
            partition_index=int_to_bytes(0, 4),
            error_code=int_to_bytes(Errors.NO_ERROR, 2),
            high_watermark=int_to_bytes(0, 8),
            last_stable_offset=int_to_bytes(0, 8),
            log_start_offset=int_to_bytes(0, 8),
            aborted_transactions=b"\x01",
            preferred_read_replica=int_to_bytes(0xFFFFFFFF, 4),
            records=records,
            tag_buffer=b"\x00",
        )

    def test_null_records_encoded_as_zero(self):
        part = self._make_partition(b"\x00")
        assert b"\x00" in part.get_bytes()

    def test_records_encoded_with_uvarint_length(self):
        payload = b"hello"
        part = self._make_partition(payload)
        data = part.get_bytes()
        # Should contain encode_uvarint(6) followed by the payload
        assert encode_uvarint(len(payload) + 1) + payload in data

    def test_aborted_transactions_empty(self):
        part = self._make_partition(b"\x00")
        data = part.get_bytes()
        # byte at offset 30 (4+2+8+8+8=30) should be 0x01 (empty compact array)
        assert data[30:31] == b"\x01"

    def test_preferred_read_replica_minus_one(self):
        part = self._make_partition(b"\x00")
        data = part.get_bytes()
        # preferred_read_replica is at offset 31 (4+2+8+8+8+1=31)
        assert data[31:35] == int_to_bytes(0xFFFFFFFF, 4)

    def test_error_code_unknown_topic(self):
        part = FetchResponsePartition(
            partition_index=int_to_bytes(0, 4),
            error_code=int_to_bytes(Errors.UNKNOWN_TOPIC_ID, 2),
            high_watermark=int_to_bytes(0, 8),
            last_stable_offset=int_to_bytes(0, 8),
            log_start_offset=int_to_bytes(0, 8),
            aborted_transactions=b"\x01",
            preferred_read_replica=int_to_bytes(0xFFFFFFFF, 4),
            records=b"\x00",
            tag_buffer=b"\x00",
        )
        data = part.get_bytes()
        assert bytes_to_int(data[4:6]) == Errors.UNKNOWN_TOPIC_ID


class TestFetchResponseTopicGetBytes:
    def test_topic_id_at_start(self):
        topic = FetchResponseTopic(
            topic_id=TOPIC_UUID,
            topic_name=None,
            partitions=[
                FetchResponsePartition(
                    int_to_bytes(0, 4), int_to_bytes(0, 2),
                    int_to_bytes(0, 8), int_to_bytes(0, 8), int_to_bytes(0, 8),
                    b"\x01", int_to_bytes(0xFFFFFFFF, 4), b"\x00", b"\x00",
                )
            ],
        )
        data = topic.get_bytes(api_version=16)
        assert data[:16] == TOPIC_UUID

    def test_partition_count_encoded(self):
        partitions = [
            FetchResponsePartition(
                int_to_bytes(i, 4), int_to_bytes(0, 2),
                int_to_bytes(0, 8), int_to_bytes(0, 8), int_to_bytes(0, 8),
                b"\x01", int_to_bytes(0xFFFFFFFF, 4), b"\x00", b"\x00",
            )
            for i in range(3)
        ]
        topic = FetchResponseTopic(topic_id=TOPIC_UUID, topic_name=None, partitions=partitions)
        data = topic.get_bytes(api_version=16)
        # count is compact array: len+1, at byte 16
        assert bytes_to_int(data[16:17]) == 3 + 1


class TestHandleFetchRequest:
    def _make_request(
        self,
        topics: list[tuple[bytes, list[int]]] | None = None,
        correlation_id: int = 7,
    ) -> FetchRequest:
        raw = build_fetch_request_bytes(topics=topics or [], correlation_id=correlation_id)
        return FetchRequest(make_buffer(raw))

    def test_response_correlation_id_matches(self):
        req = self._make_request(correlation_id=99)
        cluster = make_cluster_metadata(TOPIC_UUID, b"test-topic")
        with patch("builtins.open", side_effect=OSError):
            resp = handle_fetch_request(req, cluster, "/tmp/logs")
        assert bytes_to_int(resp.header.correlation_id) == 99

    def test_known_topic_returns_no_error(self):
        req = self._make_request(topics=[(TOPIC_UUID, [0])])
        cluster = make_cluster_metadata(TOPIC_UUID, b"test-topic")
        with patch("builtins.open", side_effect=OSError):
            resp = handle_fetch_request(req, cluster, "/tmp/logs")
        assert len(resp.body.responses) == 1
        partition = resp.body.responses[0].partitions[0]
        assert bytes_to_int(partition.error_code) == Errors.NO_ERROR

    def test_unknown_topic_returns_unknown_topic_id_error(self):
        req = self._make_request(topics=[(UNKNOWN_UUID, [0])])
        cluster = make_cluster_metadata(TOPIC_UUID, b"test-topic")
        resp = handle_fetch_request(req, cluster, "/tmp/logs")
        assert len(resp.body.responses) == 1
        partition = resp.body.responses[0].partitions[0]
        assert bytes_to_int(partition.error_code) == Errors.UNKNOWN_TOPIC_ID

    def test_no_topics_returns_empty_responses(self):
        req = self._make_request(topics=[])
        cluster = make_cluster_metadata(TOPIC_UUID, b"test-topic")
        resp = handle_fetch_request(req, cluster, "/tmp/logs")
        assert resp.body.responses == []

    def test_log_file_read_when_present(self, tmp_path):
        log_dir = tmp_path / "test-topic-0"
        log_dir.mkdir()
        log_file = log_dir / "00000000000000000000.log"
        # Minimal valid batch: base_offset=0, batch_length=49, 45 padding bytes,
        # record_count=1 at byte 57 (pos 0+57), followed by 4 bytes.
        # Layout: [base_offset:8][batch_length:4][body:49]
        # record_count sits at body offset 45 (absolute 57): pad 45 bytes then record_count=1
        body = b"\x00" * 45 + (1).to_bytes(4, "big")
        log_data = (0).to_bytes(8, "big") + len(body).to_bytes(4, "big") + body
        log_file.write_bytes(log_data)

        req = self._make_request(topics=[(TOPIC_UUID, [0])])
        cluster = make_cluster_metadata(TOPIC_UUID, b"test-topic")
        resp = handle_fetch_request(req, cluster, str(tmp_path))
        partition = resp.body.responses[0].partitions[0]
        assert partition.records == log_data

    def test_missing_log_file_returns_null_records(self):
        req = self._make_request(topics=[(TOPIC_UUID, [0])])
        cluster = make_cluster_metadata(TOPIC_UUID, b"test-topic")
        with patch("builtins.open", side_effect=OSError):
            resp = handle_fetch_request(req, cluster, "/nonexistent")
        partition = resp.body.responses[0].partitions[0]
        assert partition.records == b"\x00"

    def test_response_body_throttle_time_is_zero(self):
        req = self._make_request()
        cluster = make_cluster_metadata(TOPIC_UUID, b"test-topic")
        resp = handle_fetch_request(req, cluster, "/tmp/logs")
        assert bytes_to_int(resp.body.throttle_time) == 0

    def test_response_body_error_code_is_no_error(self):
        req = self._make_request()
        cluster = make_cluster_metadata(TOPIC_UUID, b"test-topic")
        resp = handle_fetch_request(req, cluster, "/tmp/logs")
        assert bytes_to_int(resp.body.error_code) == Errors.NO_ERROR

    def test_get_size_matches_get_bytes_length(self):
        req = self._make_request(topics=[(TOPIC_UUID, [0])])
        cluster = make_cluster_metadata(TOPIC_UUID, b"test-topic")
        with patch("builtins.open", side_effect=OSError):
            resp = handle_fetch_request(req, cluster, "/tmp/logs")
        assert resp.get_size() == len(resp.get_bytes())

    def test_multiple_topics_mixed_known_unknown(self):
        req = self._make_request(topics=[(TOPIC_UUID, [0]), (UNKNOWN_UUID, [0])])
        cluster = make_cluster_metadata(TOPIC_UUID, b"test-topic")
        with patch("builtins.open", side_effect=OSError):
            resp = handle_fetch_request(req, cluster, "/tmp/logs")
        assert len(resp.body.responses) == 2
        errors = [bytes_to_int(t.partitions[0].error_code) for t in resp.body.responses]
        assert Errors.NO_ERROR in errors
        assert Errors.UNKNOWN_TOPIC_ID in errors
