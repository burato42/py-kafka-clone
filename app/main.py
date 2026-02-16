import socket  # noqa: F401

from app.logging import logger

class Errors:
    CODE: int = 35


class WireProtocol:
    # TODO This implementation does't make sense, improve when the implementation is clear
    # 4 bytes is the size of the message in the protocol
    MESSAGE_SIZE = 4
    CORRRELATION_ID = 4
    REQUEST_API_KEY = 2
    REQUEST_API_VERSION = 2

    @staticmethod
    def message_size(size: int) -> bytes:
        return size.to_bytes(WireProtocol.MESSAGE_SIZE, 'big')
    
    @staticmethod
    def response_header_v0(number: int) -> bytes:
        return number.to_bytes(WireProtocol.MESSAGE_SIZE, 'big')
    
    @staticmethod
    def response_header_v2(number: int) -> bytes:
        response: bytes = b""
        response += number.to_bytes(WireProtocol.MESSAGE_SIZE, 'big')
        return response
    
    @staticmethod
    def get_correlation_id(number: int) -> bytes:
        return number.to_bytes(WireProtocol.CORRRELATION_ID, 'big')
    
    @staticmethod
    def get_request_api_key(number: int) -> bytes:
        return number.to_bytes(WireProtocol.REQUEST_API_KEY, 'big')
    
    @staticmethod
    def get_request_api_version(number:int) -> bytes:
        return number.to_bytes(WireProtocol.REQUEST_API_VERSION, 'big')
    

def main():
    print("Logs from your program will appear here!")


    server = socket.create_server(("localhost", 9092), reuse_port=True)
    server.listen()
    
    while True:
        socket_obj, details = server.accept()
        logger.info("Connection accepted...client details: {}", details)

        message_size = socket_obj.recv(WireProtocol.MESSAGE_SIZE)
        logger.info("Message received: {}", message_size)

        api_key = socket_obj.recv(WireProtocol.REQUEST_API_KEY)
        logger.info("Message received: {}", api_key)

        api_version = socket_obj.recv(WireProtocol.REQUEST_API_VERSION)
        logger.info("Message received: {}", api_version)

        correlation_id = socket_obj.recv(WireProtocol.CORRRELATION_ID)
        logger.info("Message received: {}", int.from_bytes(correlation_id, "big"))
               
        logger.info("Sending response to client")
        
        socket_obj.send(message_size)
        socket_obj.send(correlation_id)
        socket_obj.send(Errors.CODE.to_bytes(2, 'big'))
        socket_obj.close()
        logger.info("Connection to client closed")
    
    


if __name__ == "__main__":
    main()
