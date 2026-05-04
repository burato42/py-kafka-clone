import json
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
from app.messages.describe_topic_part import (
    handle_describe_topic_partition_request,
    DescribeTopicPartitionsRequest,
)
from app.messages.fetch import FetchRequest, handle_fetch_request
from app.messages.headers import RequestHeaderV2
from app.messages.mapping import APIKEYS
from app.protocol import (
    WireProtocol,
    bytes_to_int,
    int_to_bytes,
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
            payload = handle_api_version_request(cast(ApiVersionRequest, request))
        case ApiKeyConstants.DESCRIBE_TOPIC_PARTITION:
            payload = handle_describe_topic_partition_request(
                cast(DescribeTopicPartitionsRequest, request), configuration
            )
        case ApiKeyConstants.FETCH:
            payload = handle_fetch_request(cast(FetchRequest, request))
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
