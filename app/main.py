import json
import socket
import threading

from app.connection import Reader, Buffer
from app.logging import logger
from app.messages.api_version import (
    ApiVersionResponse,
    ApiVersionResponseBody,
)
from app.messages.api_key import (
    api_version_key,
    describe_topic_partiition_key,
    ApiKeyConstants,
)
from app.messages.describe_topic_part import (
    DescribeTopicPartitionsResponseV0,
    DescribeTopicPartitionResponseBody,
    Topic,
    TopicName,
)
from app.messages.headers import RequestHeaderV2, ResponseHeaderV0, ResponseHeaderV1
from app.messages.mapping import APIKEYS
from app.protocol import (
    WireProtocol,
    Errors,
    bytes_to_int,
    int_to_bytes,
    int_to_bytes_signed,
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


# TODO Split this function.
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
    correlation_id = header.correlation_id

    if (
        api_key == ApiKeyConstants.API_VERSION
        and 4 >= bytes_to_int(header.api_version) >= 0
    ):
        payload = ApiVersionResponse(
            ResponseHeaderV0(correlation_id),
            ApiVersionResponseBody(
                int_to_bytes(Errors.NO_ERROR, WireProtocol.ERROR_BYTES),
                [api_version_key, describe_topic_partiition_key],
                int_to_bytes(0, WireProtocol.TIME_BYTES),
                int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
            ),
        )
        socket_obj.sendall(
            int_to_bytes(payload.get_size(), WireProtocol.MESSAGE_SIZE_BYTES)
            + payload.get_bytes()
        )
    elif api_key == ApiKeyConstants.API_VERSION:
        payload = ApiVersionResponse(
            ResponseHeaderV0(correlation_id),
            ApiVersionResponseBody(
                int_to_bytes(Errors.UNSUPPORTED_VERSION, WireProtocol.ERROR_BYTES),
                [],
                int_to_bytes(0, WireProtocol.TIME_BYTES),
                int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
            ),
        )
        socket_obj.sendall(
            int_to_bytes(payload.get_size(), WireProtocol.MESSAGE_SIZE_BYTES)
            + payload.get_bytes()
        )
    elif api_key == ApiKeyConstants.DESCRIBE_TOPIC_PARTITION:
        # TODO Seems not a good place for this block
        try:
            with open(configuration["cluster_metadata_file"], "r") as metadata_file:
                cluster_metadata = json.loads(metadata_file.read())
        except (FileNotFoundError, FileExistsError) as e:
            logger.error("Cannot find or read cluster metadata: {}", e)
        except Exception as e:
            logger.error("There is an error during getting cluster metadata: {}", e)

        topic_name = request.body.topics_array[0].topic_name
        payload = DescribeTopicPartitionsResponseV0(
            ResponseHeaderV1(
                correlation_id, int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES)
            ),
            DescribeTopicPartitionResponseBody(
                int_to_bytes(0, WireProtocol.TIME_BYTES),
                [
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
                ],
                int_to_bytes_signed(-1, WireProtocol.CURSOR_BYTES),
                int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
            ),
        )
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
