from dataclasses import dataclass


from app.connection import Buffer
from app.logging import logger
from app.protocol import bytes_to_int


def read_record(buffer: Buffer) -> RecordBatch:
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
    records = []
    for _ in range(record_length):
        length = buffer.read_bytes(1)
        attributes = buffer.read_bytes(1)
        timestamp_delta = buffer.read_bytes(1)
        offset_delta = buffer.read_bytes(1)
        key_length_raw = buffer.read_bytes(1)
        key_length = bytes_to_int(key_length_raw) - 1 #The key_length is set to 0 for now  
        # key: bytes Ignore for now
        value_length_raw = buffer.read_bytes(1)
        frame_version = buffer.read_bytes(1)
        type = buffer.read_bytes(1)
        version = buffer.read_bytes(1)
        name_length_raw = buffer.read_bytes(1)
        name_length = bytes_to_int(name_length_raw) - 1
        name = buffer.read_bytes(name_length)
        feature_level = buffer.read_bytes(2)
        tagged_fields_count = buffer.read_bytes(1)

        value = Value(
            frame_version,
            type,
            version,
            name,
            feature_level,
            tagged_fields_count
        )
        headers_array_count = buffer.read_bytes(1)
        records.append(
            Record(
                length,
                attributes,
                timestamp_delta,
                offset_delta,
                b"",
                value,
                headers_array_count
            )
        )
    return RecordBatch(
        base_offset_raw,
        batch_length_raw,
        partition_leader_epoch_raw,
        magic_byte_raw,
        crc_raw,
        attributes_raw,
        last_offset_delta_raw,
        base_timestamp_raw,
        max_timestamp_raw,
        producer_id_raw,
        producer_epoch_raw,
        base_sequence_raw,
        records,
    )


def read_cluster_metadata_log(buffer: Buffer) -> ClusterMetadataLogFile:
    batches = []
    while buffer.position < buffer.message_size:
        try:
            batches.append(read_record(buffer))
        except Exception as e:
            logger.error("Didn't manage to parse all the arguments: {}", e)
    
    return ClusterMetadataLogFile(batches)


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
    # key_length: bytes
    key: bytes
    # value_length:bytes
    value: Value
    headers_array_count: bytes


@dataclass
class Value:
    frame_version: bytes
    type: bytes
    version: bytes
    name: bytes
    feature_level: bytes
    tagged_fields_count: bytes
