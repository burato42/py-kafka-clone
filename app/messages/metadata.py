from dataclasses import dataclass

from app.messages import ApiRequest, ApiResponse
from app.messages.cluster_metadata_log import (
    ClusterMetadataLogFile,
    PartitionRecordValue,
    TopicRecordValue,
)
from app.messages.headers import RequestHeader, ResponseHeaderV0
from app.protocol import Errors, bytes_to_int, int_to_bytes


BROKER_NODE_ID = 1
BROKER_HOST = b"localhost"
BROKER_PORT = 9092


@dataclass
class MetadataRequestBody:
    topics: list[bytes] | None  # None = all topics


class MetadataRequest(ApiRequest):
    header: RequestHeader
    body: MetadataRequestBody

    def get_header(self) -> RequestHeader:
        return self.read_header()

    def get_body(self) -> MetadataRequestBody:
        api_version = bytes_to_int(self.header.api_version)
        # v0–v3: Array(String) — 4-byte count, then each string as 2-byte len + bytes
        # null array (count = -1 as int32) means "all topics"
        count_raw = self.buffer.read_bytes(4)
        count = int.from_bytes(count_raw, "big", signed=True)
        if count < 0:
            topics = None
        else:
            topics = []
            for _ in range(count):
                name_len_raw = self.buffer.read_bytes(2)
                name_len = bytes_to_int(name_len_raw)
                topics.append(bytes(self.buffer.read_bytes(name_len)))
        # v4+ adds allow_auto_topic_creation (1 byte boolean)
        if api_version >= 4:
            self.buffer.read_bytes(1)
        # v8+ adds two more boolean fields
        if api_version >= 8:
            self.buffer.read_bytes(2)
        return MetadataRequestBody(topics)


def _encode_string(s: bytes) -> bytes:
    return int_to_bytes(len(s), 2) + s


def _encode_array(items: list[bytes]) -> bytes:
    return int_to_bytes(len(items), 4) + b"".join(items)


@dataclass
class MetadataResponseBody:
    api_version: int
    brokers: list[tuple]   # (node_id, host, port)
    cluster_id: bytes
    controller_id: int
    topics: list[dict]     # parsed topic+partition info

    def get_bytes(self) -> bytes:
        """
        Diffeernt content for different versions. 
        It might be processed using OOP-style approach but for now it's sufficient.
        """
        result = b""

        if self.api_version >= 3:
            result += int_to_bytes(0, 4)

        # brokers array
        broker_entries = []
        for node_id, host, port in self.brokers:
            entry = int_to_bytes(node_id, 4) + _encode_string(host) + int_to_bytes(port, 4)
            if self.api_version >= 1:
                entry += _encode_string(b"")  # rack = null string, but null is -1; use empty
            broker_entries.append(entry)
        result += _encode_array(broker_entries)

        if self.api_version >= 2:
            result += _encode_string(self.cluster_id)

        if self.api_version >= 1:
            result += int_to_bytes(self.controller_id, 4)

        topic_entries = []
        for t in self.topics:
            entry = (
                int_to_bytes(t["error_code"], 2)
                + _encode_string(t["name"])
            )
            if self.api_version >= 1:
                entry += int_to_bytes(0, 1)  # is_internal = false
            partitions = []
            for p in t["partitions"]:
                pe = (
                    int_to_bytes(p["error_code"], 2)
                    + int_to_bytes(p["partition_id"], 4)
                    + int_to_bytes(p["leader"], 4)
                )
                if self.api_version >= 7:
                    pe += int_to_bytes(p["leader_epoch"], 4)
                replicas = b"".join(int_to_bytes(r, 4) for r in p["replicas"])
                pe += int_to_bytes(len(p["replicas"]), 4) + replicas
                isr = b"".join(int_to_bytes(r, 4) for r in p["isr"])
                pe += int_to_bytes(len(p["isr"]), 4) + isr
                if self.api_version >= 5:
                    pe += int_to_bytes(0, 4)  # offline_replicas = empty array
                partitions.append(pe)
            entry += int_to_bytes(len(partitions), 4) + b"".join(partitions)
            if self.api_version >= 8:
                entry += int_to_bytes(0, 4)  # topic authorized_operations
            topic_entries.append(entry)
        result += _encode_array(topic_entries)

        if self.api_version >= 8:
            result += int_to_bytes(0, 4)  # cluster authorized_operations

        return result


@dataclass
class MetadataResponse(ApiResponse):
    header: ResponseHeaderV0
    body: MetadataResponseBody


def handle_metadata_request(
    request: MetadataRequest,
    cluster_metadata: ClusterMetadataLogFile,
) -> MetadataResponse:
    api_version = bytes_to_int(request.header.api_version)
    requested = request.body.topics  # None = all

    topic_names: dict[bytes, bytes] = {}   # uuid -> name
    topic_partitions: dict[bytes, list] = {}  # uuid -> list of partition dicts

    for batch in cluster_metadata.record_batches:
        for record in batch.records:
            val = record.value
            if isinstance(val, TopicRecordValue):
                uuid = bytes(val.topic_uuid)
                name = bytes(val.topic_name)
                if requested is None or name in requested:
                    topic_names[uuid] = name
                    topic_partitions.setdefault(uuid, [])
            elif isinstance(val, PartitionRecordValue):
                uuid = bytes(val.topic_uuid)
                if uuid in topic_names:
                    replicas = [bytes_to_int(r) for r in val.replica_array]
                    isr = [bytes_to_int(r) for r in val.in_sync_replica_array]
                    topic_partitions[uuid].append({
                        "error_code": Errors.NO_ERROR,
                        "partition_id": bytes_to_int(val.partition_id),
                        "leader": BROKER_NODE_ID,
                        "leader_epoch": bytes_to_int(val.leader_epoch),
                        "replicas": replicas if replicas else [BROKER_NODE_ID],
                        "isr": isr if isr else [BROKER_NODE_ID],
                    })

    topics = []
    for uuid, name in topic_names.items():
        topics.append({
            "error_code": Errors.NO_ERROR,
            "name": name,
            "partitions": topic_partitions[uuid],
        })

    if requested is not None:
        found = {t["name"] for t in topics}
        for name in requested:
            if name not in found:
                topics.append({
                    "error_code": Errors.UNKNOWN_TOPIC_OR_PARTITION,
                    "name": name,
                    "partitions": [],
                })

    return MetadataResponse(
        ResponseHeaderV0(request.header.correlation_id),
        MetadataResponseBody(
            api_version=api_version,
            brokers=[(BROKER_NODE_ID, BROKER_HOST, BROKER_PORT)],
            cluster_id=b"local-cluster",
            controller_id=BROKER_NODE_ID,
            topics=topics,
        ),
    )
