import json
import socket
import threading

from app.connection import Reader, Buffer
from app.logging import logger
from app.messages import ApiResponse
from app.messages.api_version import (
    ApiVersionResponse,
    ApiVersionResponseBody,
    ApiVersionRequest,
)
from app.messages.api_key import (
    api_version_key,
    describe_topic_partiition_key,
    ApiKeyConstants,
)
from app.messages.cluster_metadata_log import read_cluster_metadata_log
from app.messages.describe_topic_part import (
    DescribeTopicPartitionsResponseV0,
    DescribeTopicPartitionResponseBody,
    Topic,
    TopicName,
    Partition,
    DescribeTopicPartitionsRequest,
)
from app.messages.headers import RequestHeaderV2, ResponseHeaderV0, ResponseHeaderV1
from app.messages.mapping import APIKEYS
from app.protocol import (
    WireProtocol,
    Errors,
    bytes_to_int,
    int_to_bytes,
    int_to_bytes_signed,
    ValueTypes,
)


with open("config/config.json") as config_file:
    configuration = json.loads(config_file.read())


def handle_client(socket_obj: socket.socket, details: tuple):
    logger.info("Connection accepted from {}", details)
    try:
        while True:
            reader = Reader(socket_obj)
            try:
                size, payload = reader.read_full_message()
            except EOFError:
                logger.info("Client {} closed the connection.", details)
                break

            buffer = Buffer(size, payload)
            process_request(socket_obj, buffer)

    except Exception as e:
        logger.error("Error handling client {}: {}", details, e)
    finally:
        socket_obj.close()
        logger.info("Connection to {} closed", details)


def handle_api_version_request(request: ApiVersionRequest) -> ApiResponse:
    header: RequestHeaderV2 = request.header
    correlation_id = header.correlation_id
    logger.info("Received API Version request from client ID: {}", header.client_id)
    if 4 >= bytes_to_int(header.api_version) >= 0:
        payload = ApiVersionResponse(
            ResponseHeaderV0(correlation_id),
            ApiVersionResponseBody(
                int_to_bytes(Errors.NO_ERROR, WireProtocol.ERROR_BYTES),
                [api_version_key, describe_topic_partiition_key],
                int_to_bytes(0, WireProtocol.TIME_BYTES),
                int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
            ),
        )
    else:
        payload = ApiVersionResponse(
            ResponseHeaderV0(correlation_id),
            ApiVersionResponseBody(
                int_to_bytes(Errors.UNSUPPORTED_VERSION, WireProtocol.ERROR_BYTES),
                [],
                int_to_bytes(0, WireProtocol.TIME_BYTES),
                int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
            ),
        )

    return payload


def handle_describe_topic_partition_request(
    request: DescribeTopicPartitionsRequest,
) -> ApiResponse:
    try:
        with open(configuration["cluster_metadata_file"], "rb") as metadata_file:
            cluster_metadata = metadata_file.read()
            metadata_buffer = Buffer(len(cluster_metadata), cluster_metadata)
            metadata_log = read_cluster_metadata_log(metadata_buffer)
            logger.debug(metadata_log)

    except (FileNotFoundError, FileExistsError) as e:
        logger.error("Cannot find or read cluster metadata: {}", e)
    except Exception as e:
        logger.error("There is an error during getting cluster metadata: {}", e)

    topic_name = request.body.topics_array[0].topic_name

    topics: dict[bytes, Topic] = {}

    # TODO Is this a good way to parse the topic? Fix it.
    for record_batch in metadata_log.record_batches:
        for record in record_batch.records:
            logger.debug(
                "Checking record with type {} for topic {}", bytes_to_int(record.value.type), topic_name
            )
            if bytes_to_int(record.value.type) == ValueTypes.TOPIC_RECORD_VALUE:
                topic_name_bytes = record.value.topic_name
                if topic_name_bytes == topic_name:
                    logger.info("Found topic {} in cluster metadata log", topic_name)
                    if record.value.topic_uuid not in topics:
                        topics[record.value.topic_uuid] = Topic(
                            int_to_bytes(Errors.NO_ERROR, WireProtocol.ERROR_BYTES),
                            TopicName(topic_name),
                            record.value.topic_uuid,
                            int_to_bytes(0, WireProtocol.BOOLEAN_BYTES),
                            [
                                Partition(
                                    int_to_bytes(
                                        Errors.NO_ERROR, WireProtocol.ERROR_BYTES
                                    ),
                                    int_to_bytes(0, 4),
                                    int_to_bytes(1, 4),
                                    int_to_bytes(0, 4),
                                    [int_to_bytes(1, 2)],
                                    [int_to_bytes(1, 2)],
                                    [],
                                    [],
                                    [],
                                    int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
                                )
                            ],
                            int_to_bytes(0, WireProtocol.TOPIC_AUTH_OPS_BYTES),
                            int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
                        )
            if bytes_to_int(record.value.type) == ValueTypes.PARTITION_RECORD_VALUE:
                topic_uuid = record.value.topic_uuid
                print(
                    f"Checking partition record for topic {topic_name} with uuid {topic_uuid}"
                )
                if topic_uuid in topics:
                    partition = Partition(
                        int_to_bytes(Errors.NO_ERROR, WireProtocol.ERROR_BYTES),
                        record.value.partition_id,
                        record.value.leader,
                        record.value.leader_epoch,
                        record.value.replica_array,
                        record.value.in_sync_replica_array,
                        record.value.adding_replicas_array,
                        record.value.removing_replicas_array,
                        [],
                        int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
                    )
                    print(f"Partition found for topic {topic_name}: {partition}")
                    topics[topic_uuid].partitions_array.append(partition)

    topic_content = list(topics.values())

    if not topics:
        logger.info("Topic {} not found in cluster metadata log", topic_name)
        topic_content = [
            Topic(
                int_to_bytes(
                    Errors.UNKNOWN_TOPIC_OR_PARTITION, WireProtocol.ERROR_BYTES
                ),
                TopicName(topic_name),
                int_to_bytes(0, WireProtocol.TOPIC_ID_BYTES),
                int_to_bytes(0, WireProtocol.BOOLEAN_BYTES),
                [],
                int_to_bytes(0, WireProtocol.TOPIC_AUTH_OPS_BYTES),
                int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
            )
        ]

    payload = DescribeTopicPartitionsResponseV0(
        ResponseHeaderV1(
            request.header.correlation_id,
            int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
        ),
        DescribeTopicPartitionResponseBody(
            int_to_bytes(0, WireProtocol.TIME_BYTES),
            topic_content,
            int_to_bytes_signed(-1, WireProtocol.CURSOR_BYTES),
            int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
        ),
    )
    return payload


def process_request(socket_obj: socket.socket, buffer: Buffer):
    raw_api_key = buffer.peek_bytes(WireProtocol.REQUEST_API_KEY_BYTES)

    api_key = bytes_to_int(raw_api_key)

    if api_key not in APIKEYS:
        logger.error("Unknown API key {}", api_key)
        return

    logger.info("Request API key: {}; Request type: {}", api_key, APIKEYS[api_key])
    kls = APIKEYS[api_key]
    request = kls(buffer)
    header: RequestHeaderV2 = request.header
    payload = None

    match api_key:
        case ApiKeyConstants.API_VERSION:
            payload = handle_api_version_request(request)
        case ApiKeyConstants.DESCRIBE_TOPIC_PARTITION:
            payload = handle_describe_topic_partition_request(request)
        case _:
            logger.error(
                "Unsupported API key {} or API version {}", api_key, header.api_version
            )

    if not payload:
        logger.error(
            "Unsupported API key {} or API version {}", api_key, header.api_version
        )
        return

    socket_obj.sendall(
        int_to_bytes(payload.get_size(), WireProtocol.MESSAGE_SIZE_BYTES)
        + payload.get_bytes()
    )


def main():
    server = socket.create_server(("localhost", 9092), reuse_port=True)
    server.listen()

    while True:
        socket_obj, details = server.accept()
        logger.info("Connection accepted...client details: {}", details)

        client_thread = threading.Thread(
            target=handle_client, args=(socket_obj, details), daemon=True
        )
        client_thread.start()


if __name__ == "__main__":
    main()
