import pytest

from app.connection import Buffer
from app.messages.cluster_metadata_log import (
    ClusterMetadataLogFile,
    FeatureLevelRecordValue,
    PartitionRecordValue,
    RecordBatch,
    TopicRecordValue,
    UnregisterBrokerRecordValue,
    Value,
    get_cluster_metadata,
    get_config,
    read_cluster_metadata_log,
    read_record,
)
from tests.conftest import make_buffer


def _encode_zigzag(n: int) -> bytes:
    """Encode a signed integer as a single-byte zigzag varint (values -64..63)."""
    raw = (n << 1) ^ (n >> 63)
    assert raw < 0x80, "use a multi-byte encoder for larger values"
    return bytes([raw])


def _build_feature_level_value(name: bytes = b"kraft", feature_level: int = 1) -> bytes:
    """Build the bytes that follow frame_version+type_raw for a FeatureLevelRecord."""
    name_len = len(name) + 1  # compact string: actual_len + 1
    return (
        b"\x01"                          # version
        + bytes([name_len])              # name length (compact)
        + name                           # name bytes
        + feature_level.to_bytes(2, "big")  # feature_level
        + b"\x00"                        # tagged_fields_count
    )


def _build_topic_value(topic_name: bytes = b"my-topic", topic_uuid: bytes = bytes(16)) -> bytes:
    name_len = len(topic_name) + 1
    return (
        b"\x01"                    # version
        + bytes([name_len])        # name length (compact)
        + topic_name               # name
        + topic_uuid               # 16-byte UUID
        + b"\x00"                  # tagged_fields_count
    )


def _build_partition_value(
    partition_id: int = 0,
    topic_uuid: bytes = bytes(16),
) -> bytes:
    return (
        b"\x01"                                  # version
        + partition_id.to_bytes(4, "big")        # partition_id
        + topic_uuid                             # topic_uuid (16 bytes)
        + b"\x01"                                # replica_array length (compact: 1 → 0 items)
        + b"\x01"                                # in_sync_replica_array length (0 items)
        + b"\x01"                                # removing_replicas_array length (0 items)
        + b"\x01"                                # adding_replicas_array length (0 items)
        + (1).to_bytes(4, "big")                 # leader
        + (0).to_bytes(4, "big")                 # leader_epoch
        + (0).to_bytes(4, "big")                 # partition_epoch
        + b"\x01"                                # directories_array length (0 items)
        + b"\x00"                                # tagged_fields_count
    )


def _build_unregister_broker_value(broker_id: int = 1) -> bytes:
    return (
        b"\x01"                            # version
        + broker_id.to_bytes(4, "big")    # broker_id
        + (0).to_bytes(8, "big")           # broker_epoch
        + b"\x00"                          # tagged_fields_count
    )


def _build_record(value_type: bytes, value_bytes: bytes) -> bytes:
    """Build a single Record's bytes inside a RecordBatch records array."""
    inner = (
        b"\x00"                        # attributes
        + _encode_zigzag(0)            # timestamp_delta
        + _encode_zigzag(0)            # offset_delta
        + _encode_zigzag(-1)           # key_length < 0 → no key bytes
        + _encode_zigzag(0)            # value_length varint (unused — reads fixed fields)
        + b"\x01"                      # frame_version
        + value_type                   # type byte
        + value_bytes                  # actual value payload
        + b"\x00"                      # headers_array_count
    )
    length_varint = _encode_zigzag(len(inner))
    return length_varint + inner


def _build_batch(records_payload: bytes, record_count: int) -> bytes:
    """Wrap records_payload in a full RecordBatch binary structure."""
    # Fields after batch_length (which starts at partition_leader_epoch):
    inner = (
        b"\x00\x00\x00\x00"            # partition_leader_epoch
        + b"\x02"                      # magic_byte
        + b"\x00\x00\x00\x00"         # crc
        + b"\x00\x00"                  # attributes
        + b"\x00\x00\x00\x00"         # last_offset_delta
        + b"\x00" * 8                  # base_timestamp
        + b"\x00" * 8                  # max_timestamp
        + b"\x00" * 8                  # producer_id
        + b"\x00\x00"                  # producer_epoch
        + b"\x00\x00\x00\x00"         # base_sequence
        + record_count.to_bytes(4, "big")  # record count
        + records_payload
    )
    return (
        b"\x00\x00\x00\x00\x00\x00\x00\x00"  # base_offset (8 bytes)
        + len(inner).to_bytes(4, "big")        # batch_length
        + inner
    )


# ---------------------------------------------------------------------------
# FeatureLevelRecordValue
# ---------------------------------------------------------------------------

class TestFeatureLevelRecordValue:
    def test_parse_basic(self):
        data = _build_feature_level_value(name=b"kraft", feature_level=3)
        buf = make_buffer(data)
        v = FeatureLevelRecordValue.parse_data(buf, b"\x01")
        assert v.name == b"kraft"
        assert v.feature_level == (3).to_bytes(2, "big")
        assert v.type == b"\x0c"

    def test_tagged_fields_count_read(self):
        data = _build_feature_level_value()
        buf = make_buffer(data)
        v = FeatureLevelRecordValue.parse_data(buf, b"\x01")
        assert v.tagged_fields_count == b"\x00"


# ---------------------------------------------------------------------------
# TopicRecordValue
# ---------------------------------------------------------------------------

class TestTopicRecordValue:
    def test_parse_topic_name(self):
        uuid = bytes(range(16))
        data = _build_topic_value(topic_name=b"orders", topic_uuid=uuid)
        buf = make_buffer(data)
        v = TopicRecordValue.parse_data(buf, b"\x01")
        assert v.topic_name == b"orders"
        assert v.topic_uuid == uuid
        assert v.type == b"\x02"


# ---------------------------------------------------------------------------
# PartitionRecordValue
# ---------------------------------------------------------------------------

class TestPartitionRecordValue:
    def test_parse_partition_id(self):
        data = _build_partition_value(partition_id=7)
        buf = make_buffer(data)
        v = PartitionRecordValue.parse_data(buf, b"\x01")
        assert v.partition_id == (7).to_bytes(4, "big")
        assert v.replica_array == []
        assert v.type == b"\x03"

    def test_parse_with_replicas(self):
        # replica_array with 2 items → compact length = 3
        replicas = (1).to_bytes(4, "big") + (2).to_bytes(4, "big")
        data = (
            b"\x01"                                  # version
            + (0).to_bytes(4, "big")                 # partition_id
            + bytes(16)                              # topic_uuid
            + b"\x03"                                # replica_array length (2 items)
            + replicas
            + b"\x01"                                # in_sync_replica_array (0)
            + b"\x01"                                # removing_replicas (0)
            + b"\x01"                                # adding_replicas (0)
            + (1).to_bytes(4, "big")                 # leader
            + (0).to_bytes(4, "big")                 # leader_epoch
            + (0).to_bytes(4, "big")                 # partition_epoch
            + b"\x01"                                # directories (0)
            + b"\x00"                                # tagged_fields_count
        )
        buf = make_buffer(data)
        v = PartitionRecordValue.parse_data(buf, b"\x01")
        assert len(v.replica_array) == 2


# ---------------------------------------------------------------------------
# UnregisterBrokerRecordValue
# ---------------------------------------------------------------------------

class TestUnregisterBrokerRecordValue:
    def test_parse_broker_id(self):
        data = _build_unregister_broker_value(broker_id=42)
        buf = make_buffer(data)
        v = UnregisterBrokerRecordValue.parse_data(buf, b"\x01")
        assert v.broker_id == (42).to_bytes(4, "big")
        assert v.type == b"\x01"


# ---------------------------------------------------------------------------
# Value.get dispatch
# ---------------------------------------------------------------------------

class TestValueDispatch:
    def test_feature_level(self):
        data = _build_feature_level_value()
        buf = make_buffer(data)
        v = Value.get(buf, b"\x01", b"\x0c")
        assert isinstance(v, FeatureLevelRecordValue)

    def test_topic(self):
        data = _build_topic_value()
        buf = make_buffer(data)
        v = Value.get(buf, b"\x01", b"\x02")
        assert isinstance(v, TopicRecordValue)

    def test_partition(self):
        data = _build_partition_value()
        buf = make_buffer(data)
        v = Value.get(buf, b"\x01", b"\x03")
        assert isinstance(v, PartitionRecordValue)

    def test_unregister_broker(self):
        data = _build_unregister_broker_value()
        buf = make_buffer(data)
        v = Value.get(buf, b"\x01", b"\x01")
        assert isinstance(v, UnregisterBrokerRecordValue)

    def test_unknown_type_raises(self):
        buf = make_buffer(b"\x00" * 32)
        with pytest.raises(Exception, match="Wrong value type"):
            Value.get(buf, b"\x01", b"\xff")


# ---------------------------------------------------------------------------
# read_record / read_cluster_metadata_log
# ---------------------------------------------------------------------------

class TestReadRecord:
    def test_read_feature_level_batch(self):
        record_payload = _build_record(b"\x0c", _build_feature_level_value())
        batch = _build_batch(record_payload, record_count=1)
        buf = make_buffer(batch)
        rb = read_record(buf)
        assert isinstance(rb, RecordBatch)
        assert len(rb.records) == 1
        assert isinstance(rb.records[0].value, FeatureLevelRecordValue)

    def test_read_topic_batch(self):
        record_payload = _build_record(b"\x02", _build_topic_value(b"t1", bytes(16)))
        batch = _build_batch(record_payload, record_count=1)
        buf = make_buffer(batch)
        rb = read_record(buf)
        assert isinstance(rb.records[0].value, TopicRecordValue)

    def test_parse_error_still_advances_position(self):
        # Put garbage bytes as value — parser should catch the error and skip to batch end
        bad_record = _build_record(b"\x0c", b"\x00")  # too short for feature level
        batch = _build_batch(bad_record, record_count=1)
        buf = make_buffer(batch)
        rb = read_record(buf)
        # Position should be at end of batch (buffer exhausted)
        assert buf.position == len(batch)


class TestReadClusterMetadataLog:
    def test_empty_buffer_returns_no_batches(self):
        buf = Buffer(0, b"")
        log = read_cluster_metadata_log(buf)
        assert isinstance(log, ClusterMetadataLogFile)
        assert log.record_batches == []

    def test_two_batches_parsed(self):
        b1 = _build_batch(_build_record(b"\x0c", _build_feature_level_value()), 1)
        b2 = _build_batch(_build_record(b"\x02", _build_topic_value()), 1)
        data = b1 + b2
        buf = Buffer(len(data), data)
        log = read_cluster_metadata_log(buf)
        assert len(log.record_batches) == 2


# ---------------------------------------------------------------------------
# get_config / get_cluster_metadata
# ---------------------------------------------------------------------------

class TestGetConfig:
    def test_reads_json_file(self, tmp_path):
        cfg = tmp_path / "cfg.json"
        cfg.write_text('{"cluster_metadata_file": "/tmp/meta"}')
        result = get_config(str(cfg))
        assert result["cluster_metadata_file"] == "/tmp/meta"


class TestGetClusterMetadata:
    def test_returns_log_file_for_valid_data(self, tmp_path):
        b1 = _build_batch(_build_record(b"\x0c", _build_feature_level_value()), 1)
        meta_file = tmp_path / "meta.bin"
        meta_file.write_bytes(b1)
        cfg_file = tmp_path / "cfg.json"
        cfg_file.write_text(f'{{"cluster_metadata_file": "{meta_file}"}}')
        result = get_cluster_metadata(str(cfg_file))
        assert isinstance(result, ClusterMetadataLogFile)
        assert len(result.record_batches) == 1

    def test_returns_none_on_missing_metadata_file(self, tmp_path):
        cfg_file = tmp_path / "cfg.json"
        cfg_file.write_text('{"cluster_metadata_file": "/nonexistent/path.bin"}')
        result = get_cluster_metadata(str(cfg_file))
        assert result is None
