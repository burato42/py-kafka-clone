from dataclasses import dataclass

from app.connection import Buffer
from app.protocol import bytes_to_int


def read_cluster_metadata_log(buffer: Buffer) -> ClusterMetadataLogFile:
    base_offset_raw = buffer.read_bytes(8)
    batch_length_raw = buffer.read_bytes(4)
    partition_leader_epoch_raw = buffer.read_bytes(4)
    magic_byte_raw = buffer.read_bytes(1)
    crc_raw = buffer.read_bytes(4)
    attributes_raw = buffer.read_bytes(2)
    last_offset_delta_raw = buffer.read_bytes(4)
    base_timestamp_raw = buffer.read_bytes(8)
    max_timestamp_raw = buffer.read_bytes(8)
    producer_id_raw = buffer.read_bytes(8)
    producer_epoch_raw = buffer.read_bytes(2)
    base_sequence_raw = buffer.read_bytes(4)
    record_length_raw = buffer.read_bytes(4)
    record_length = bytes_to_int(record_length_raw)
    for _ in range:
        ...


@dataclass
class ClusterMetadataLogFile:
    record_batches: list[RecordBatch]


@dataclass
class RecordBatch:
    base_offset: bytes
    batch_length: bytes
    partition_leader_epoch: bytes
    magic_byte: bytes
    crc: bytes
    attributes: bytes
    last_offset_delta: bytes
    base_timestamp: bytes
    max_timestamp: bytes
    producer_id: bytes
    producer_epoch: bytes
    base_sequence: bytes
    # Don't forget the length during the parsing 
    records: list[Record]
    
    
@dataclass
class Record:
    length: bytes  
    attributes: bytes
    timestamp_delta: bytes
    offset_delta: bytes
    key_length: bytes
    key: bytes
    value_length:bytes
    value: Value
    headers_array_count: bytes


@dataclass
class Value:
    frame_version: bytes
    type: bytes
    version: bytes
    name_length: bytes
    name: bytes
    feature_level: bytes
    tagged_fields_count: bytes
