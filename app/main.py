import argparse
import socket
import threading
from typing import cast

from app.connection import Reader, Buffer
from app.logging import logger
from app.messages.api_version import (
    handle_api_version_request,
    ApiVersionRequest,
)
from app.messages.api_key import (
    ApiKeyConstants,
)
from app.messages.cluster_metadata_log import (
    ClusterMetadataLogFile,
    get_cluster_metadata,
    get_config,
)
from app.messages.describe_topic_part import (
    handle_describe_topic_partition_request,
    DescribeTopicPartitionsRequest,
)
from app.messages.fetch import FetchRequest, handle_fetch_request
from app.messages.init_producer_id import (
    InitProducerIdRequest,
    handle_init_producer_id_request,
)
from app.messages.metadata import MetadataRequest, handle_metadata_request
from app.messages.produce import handle_produce_request
from app.messages.headers import RequestHeader
from app.messages.mapping import APIKEYS
from app.protocol import (
    WireProtocol,
    bytes_to_int,
    int_to_bytes,
)


def handle_client(
    socket_obj: socket.socket,
    details: tuple,
    cluster_metadata: ClusterMetadataLogFile,
    partition_log_dir: str,
):
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
            logger.debug("Received {} bytes: {}", size, payload.hex())
            process_request(socket_obj, buffer, cluster_metadata, partition_log_dir)

    except Exception as e:
        logger.exception("Error handling client {}: {}", details, e)
    finally:
        socket_obj.close()
        logger.info("Connection to {} closed", details)


def process_request(
    socket_obj: socket.socket,
    buffer: Buffer,
    cluster_metadata: ClusterMetadataLogFile,
    partition_log_dir: str,
):
    raw_api_key = buffer.peek_bytes(WireProtocol.REQUEST_API_KEY_BYTES)

    api_key = bytes_to_int(raw_api_key)

    if api_key not in APIKEYS:
        logger.error("Unknown API key {}", api_key)
        return

    logger.info("Request API key: {}; Request type: {}", api_key, APIKEYS[api_key])
    kls = APIKEYS[api_key]
    request = kls(buffer)
    header: RequestHeader = request.header
    payload = None

    match api_key:
        case ApiKeyConstants.API_VERSION:
            payload = handle_api_version_request(cast(ApiVersionRequest, request))
        case ApiKeyConstants.DESCRIBE_TOPIC_PARTITION:
            payload = handle_describe_topic_partition_request(
                cast(DescribeTopicPartitionsRequest, request), cluster_metadata
            )
        case ApiKeyConstants.FETCH:
            payload = handle_fetch_request(
                cast(FetchRequest, request), cluster_metadata, partition_log_dir
            )
        case ApiKeyConstants.INIT_PRODUCER_ID:
            payload = handle_init_producer_id_request(
                cast(InitProducerIdRequest, request)
            )
        case ApiKeyConstants.METADATA:
            payload = handle_metadata_request(
                cast(MetadataRequest, request), cluster_metadata
            )
        case ApiKeyConstants.PRODUCE:
            payload = handle_produce_request(
                request, cluster_metadata, partition_log_dir
            )
        case _:
            logger.error(
                "Unsupported API key {} or API version {}", api_key, header.api_version
            )

    if not payload:
        logger.error(
            "Unsupported API key {} or API version {}", api_key, header.api_version
        )
        return

    response_bytes = (
        int_to_bytes(payload.get_size(), WireProtocol.MESSAGE_SIZE_BYTES)
        + payload.get_bytes()
    )
    logger.debug("Sending {} bytes: {}", len(response_bytes), response_bytes.hex())
    socket_obj.sendall(response_bytes)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/dev.json")
    args, _ = parser.parse_known_args()

    server = socket.create_server(("localhost", 9092), reuse_port=True)
    server.listen()

    config = get_config(args.config)
    cluster_metadata = get_cluster_metadata(args.config) or ClusterMetadataLogFile([])
    partition_log_dir = config["partition_log_dir"]
    while True:
        socket_obj, details = server.accept()
        logger.info("Connection accepted...client details: {}", details)

        client_thread = threading.Thread(
            target=handle_client,
            args=(socket_obj, details, cluster_metadata, partition_log_dir),
            daemon=True,
        )
        client_thread.start()


if __name__ == "__main__":
    main()
