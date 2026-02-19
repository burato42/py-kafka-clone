import socket
import threading

from app.connection import Reader, Buffer
from app.logging import logger
from app.messages.api_version import (
    ApiVersionRespons,
    ApiVersionResponseBody,
)
from app.messages.api_key import api_version_key, describe_topic_partiition_key
from app.messages.headers import RequestHeader, ResponseHeader
from app.messages.mapping import APIKEYS
from app.protocol import WireProtocol, Errors, bytes_to_int, int_to_bytes


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

    if (api_key := bytes_to_int(raw_api_key)) in APIKEYS:
        logger.info("Request API key: {}; Request type: {}", api_key, APIKEYS[api_key])
        kls = APIKEYS[api_key]
        request = kls(buffer)
        header: RequestHeader = request.get_header()
        correlation_id = header.correlation_id
        if 4 >= bytes_to_int(header.api_version) >= 0:
            payload = ApiVersionRespons(
                ResponseHeader(correlation_id),
                ApiVersionResponseBody(
                    int_to_bytes(Errors.NO_ERROR, WireProtocol.ERROR_BYTES),
                    [
                        api_version_key,
                        describe_topic_partiition_key
                    ],
                    int_to_bytes(0, WireProtocol.TIME_BYTES),
                    int_to_bytes(0, WireProtocol.TAG_BUFFER_BYTES),
                ),
            )
            socket_obj.sendall(
                int_to_bytes(payload.get_size(), WireProtocol.MESSAGE_SIZE_BYTES)
                + payload.get_bytes()
            )
        else:
            payload = ApiVersionRespons(
                ResponseHeader(correlation_id),
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
    else:
        logger.info("Unknown API key {}", api_key)


def main():
    print("Logs from your program will appear here!")

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
