"""
Generate a minimal KRaft cluster metadata log file that registers one or more
topics so our broker can serve Metadata and Produce requests for them.

Usage:
    uv run tools/create_cluster_metadata.py --topic grape --partitions 2
    uv run tools/create_cluster_metadata.py --topic grape --partitions 2 --topic pear --partitions 1
    uv run tools/create_cluster_metadata.py --output /tmp/my-cluster/meta.log --topic foo
"""
import argparse
import os
import struct
import time
import uuid as uuid_mod


# ---------------------------------------------------------------------------
# CRC32C (Castagnoli) — Kafka uses this for batch checksums
# ---------------------------------------------------------------------------

_CRC32C_TABLE = []
for _i in range(256):
    _crc = _i
    for _ in range(8):
        _crc = (_crc >> 1) ^ 0x82F63B78 if _crc & 1 else _crc >> 1
    _CRC32C_TABLE.append(_crc)


def _crc32c(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for b in data:
        crc = (crc >> 8) ^ _CRC32C_TABLE[(crc ^ b) & 0xFF]
    return crc ^ 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Varint / compact-string helpers
# ---------------------------------------------------------------------------

def _zigzag(n: int) -> bytes:
    raw = (n << 1) ^ (n >> 63)
    out = []
    while True:
        b = raw & 0x7F
        raw >>= 7
        if raw:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def _uvarint(n: int) -> bytes:
    out = []
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def _compact_string(s: bytes) -> bytes:
    return _uvarint(len(s) + 1) + s


# ---------------------------------------------------------------------------
# Record builder
# ---------------------------------------------------------------------------

def _record(offset_delta: int, value_type: int, value_body: bytes) -> bytes:
    """Build a single Kafka record with the given value type byte and body."""
    payload = (
        b"\x00"                  # attributes
        + _zigzag(0)             # timestamp_delta
        + _zigzag(offset_delta)  # offset_delta
        + _zigzag(-1)            # key_length (null)
        + _zigzag(0)             # value_length varint (parser ignores, reads fixed fields)
        + b"\x01"                # frame_version
        + bytes([value_type])    # type
        + value_body
        + b"\x00"                # headers array count
    )
    return _zigzag(len(payload)) + payload


def _feature_level_record(name: bytes, level: int) -> bytes:
    body = (
        b"\x01"                      # version
        + _compact_string(name)      # name
        + struct.pack(">H", level)   # feature_level (int16)
        + b"\x00"                    # tagged_fields_count
    )
    return _record(0, 0x0C, body)


def _topic_record(name: bytes, topic_uuid: bytes) -> bytes:
    body = (
        b"\x01"                    # version
        + _compact_string(name)    # topic_name
        + topic_uuid               # uuid (16 bytes)
        + b"\x00"                  # tagged_fields_count
    )
    return _record(0, 0x02, body)


def _partition_record(partition_id: int, topic_uuid: bytes, offset_delta: int, broker_id: int = 1) -> bytes:
    bid = struct.pack(">I", broker_id)
    body = (
        b"\x01"                              # version
        + struct.pack(">I", partition_id)    # partition_id
        + topic_uuid                         # topic_uuid (16 bytes)
        + b"\x02" + bid                      # replica_array: compact length=2 (1 item), broker_id
        + b"\x02" + bid                      # in_sync_replica_array
        + b"\x01"                            # removing_replicas (empty)
        + b"\x01"                            # adding_replicas (empty)
        + bid                                # leader
        + struct.pack(">I", 0)               # leader_epoch
        + struct.pack(">I", 0)               # partition_epoch
        + b"\x01"                            # directories (empty)
        + b"\x00"                            # tagged_fields_count
    )
    return _record(offset_delta, 0x03, body)


# ---------------------------------------------------------------------------
# Batch builder
# ---------------------------------------------------------------------------

def _batch(base_offset: int, records: list[bytes], timestamp_ms: int | None = None) -> bytes:
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)

    records_payload = b"".join(records)
    record_count = len(records)

    # Fields covered by CRC: from attributes to end of batch
    crc_payload = (
        struct.pack(">H", 0)                    # attributes
        + struct.pack(">I", record_count - 1)   # last_offset_delta
        + struct.pack(">Q", timestamp_ms)        # base_timestamp
        + struct.pack(">Q", timestamp_ms)        # max_timestamp
        + struct.pack(">q", -1)                  # producer_id
        + struct.pack(">h", -1)                  # producer_epoch
        + struct.pack(">i", -1)                  # base_sequence
        + struct.pack(">I", record_count)        # record_count
        + records_payload
    )

    batch_body = (
        struct.pack(">I", 1)         # partition_leader_epoch
        + b"\x02"                    # magic
        + struct.pack(">I", _crc32c(crc_payload))
        + crc_payload
    )

    return (
        struct.pack(">Q", base_offset)
        + struct.pack(">I", len(batch_body))
        + batch_body
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _next_base_offset(path: str) -> int:
    """Scan all batches in an existing log file and return the next free base offset."""
    if not os.path.exists(path):
        return 1
    with open(path, "rb") as f:
        data = f.read()
    offset = 1
    pos = 0
    while pos + 12 <= len(data):
        base_offset = int.from_bytes(data[pos : pos + 8], "big")
        batch_length = int.from_bytes(data[pos + 8 : pos + 12], "big")
        record_count_pos = pos + 57
        if record_count_pos + 4 > len(data):
            break
        record_count = int.from_bytes(data[record_count_pos : record_count_pos + 4], "big")
        offset = base_offset + record_count
        pos += 8 + 4 + batch_length
    return offset


def generate(topics: list[tuple[str, int]], output_path: str) -> None:
    ts = int(time.time() * 1000)
    batches = []

    # Batch 0: feature level record (metadata.version = 20, matching real Kafka 3.7+)
    batches.append(_batch(1, [_feature_level_record(b"metadata.version", 20)], ts))

    # One batch per topic: topic record + N partition records
    base_offset = 2
    for topic_name, num_partitions in topics:
        name_bytes = topic_name.encode()
        topic_uuid = uuid_mod.uuid4().bytes
        records = [_topic_record(name_bytes, topic_uuid)]
        for p in range(num_partitions):
            records.append(_partition_record(p, topic_uuid, offset_delta=p + 1))
        batches.append(_batch(base_offset, records, ts))
        base_offset += 1 + num_partitions

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as f:
        for batch in batches:
            f.write(batch)

    print(f"Written {output_path} ({sum(len(b) for b in batches)} bytes)")
    for name, n in topics:
        print(f"  topic={name!r}  partitions={n}")


def append_topics(topics: list[tuple[str, int]], output_path: str) -> None:
    """Append new topic+partition records to an existing metadata log file."""
    base_offset = _next_base_offset(output_path)
    ts = int(time.time() * 1000)
    batches = []

    for topic_name, num_partitions in topics:
        name_bytes = topic_name.encode()
        topic_uuid = uuid_mod.uuid4().bytes
        records = [_topic_record(name_bytes, topic_uuid)]
        for p in range(num_partitions):
            records.append(_partition_record(p, topic_uuid, offset_delta=p + 1))
        batches.append(_batch(base_offset, records, ts))
        base_offset += 1 + num_partitions

    with open(output_path, "ab") as f:
        for batch in batches:
            f.write(batch)

    print(f"Appended to {output_path} ({sum(len(b) for b in batches)} bytes)")
    for name, n in topics:
        print(f"  topic={name!r}  partitions={n}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a KRaft cluster metadata log")
    parser.add_argument("--topic", action="append", dest="topics", metavar="NAME", required=True)
    parser.add_argument("--partitions", action="append", dest="partitions", type=int, metavar="N")
    parser.add_argument("--output", default="/tmp/kraft-combined-logs/__cluster_metadata-0/00000000000000000000.log")
    parser.add_argument("--append", action="store_true", help="Append to existing file instead of overwriting")
    args = parser.parse_args()

    partitions = args.partitions or []
    # Pad missing --partitions values with 1
    while len(partitions) < len(args.topics):
        partitions.append(1)

    topic_list = list(zip(args.topics, partitions))
    if args.append:
        append_topics(topic_list, args.output)
    else:
        generate(topic_list, args.output)
