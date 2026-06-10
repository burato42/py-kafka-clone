import argparse
import asyncio
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
from app.messages.list_offsets import ListOffsetsRequest, handle_list_offsets_request
from app.messages.metadata import MetadataRequest, handle_metadata_request
from app.messages.produce import handle_produce_request
from app.messages.headers import RequestHeader
from app.messages.mapping import APIKEYS
from app.protocol import (
    WireProtocol,
    bytes_to_int,
    int_to_bytes,
)


async def handle_client(
    reader_stream: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    cluster_metadata: ClusterMetadataLogFile,
    partition_log_dir: str,
):
    details = writer.get_extra_info("peername")
    logger.info("Connection accepted from {}", details)
    reader = Reader(reader_stream)
    try:
        while True:
            try:
                size, payload = await reader.read_full_message()
            except (EOFError, ConnectionResetError, asyncio.IncompleteReadError):
                logger.info("Client {} closed the connection.", details)
                break

            buffer = Buffer(size, payload)
            logger.debug("Received {} bytes: {}", size, payload.hex())
            await process_request(writer, buffer, cluster_metadata, partition_log_dir)

    except Exception as e:
        logger.exception("Error handling client {}: {}", details, e)
    finally:
        writer.close()
        await writer.wait_closed()
        logger.info("Connection to {} closed", details)


async def process_request(
    writer: asyncio.StreamWriter,
    buffer: Buffer,
    cluster_metadata: ClusterMetadataLogFile,
    partition_log_dir: str,
):
    raw_api_key = buffer.peek_bytes(WireProtocol.REQUEST_API_KEY_BYTES)

    api_key = bytes_to_int(raw_api_key)

    if api_key not in APIKEYS:
        logger.error("Unknown API key {}", api_key)
        return

    logger.debug("Request API key: {}; Request type: {}", api_key, APIKEYS[api_key])
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
        case ApiKeyConstants.LIST_OFFSETS:
            payload = handle_list_offsets_request(
                cast(ListOffsetsRequest, request), cluster_metadata, partition_log_dir
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
    writer.write(response_bytes)
    await writer.drain()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/dev.json")
    args, _ = parser.parse_known_args()

    config = get_config(args.config)
    cluster_metadata = get_cluster_metadata(args.config) or ClusterMetadataLogFile([])
    partition_log_dir = config["partition_log_dir"]

    async def _serve():
        server = await asyncio.start_server(
            lambda reader, writer: handle_client(reader, writer, cluster_metadata, partition_log_dir),
            "0.0.0.0",
            9092,
        )
        async with server:
            await server.serve_forever()

    asyncio.run(_serve())


if __name__ == "__main__":
    main()
