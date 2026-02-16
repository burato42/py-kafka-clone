import socket  # noqa: F401

from app.logging import logger

class Errors:
    NO_ERROR: int = 0
    UNSUPPORTED_VERSION: int = 35


class WireProtocol:
    # TODO This implementation does't make sense, improve when the implementation is clear
    # 4 bytes is the size of the message in the protocol
    MESSAGE_SIZE = 4
    CORRRELATION_ID = 4
    REQUEST_API_KEY = 2
    REQUEST_API_VERSION = 2
    TIME = 4

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
    
    @staticmethod
    def get_api_key_array_length(number: int) -> bytes:
        return number.to_bytes(1, 'big')
    
    @staticmethod
    def get_buffer(number: int) -> bytes:
        return number.to_bytes(1, 'big')
    
    @staticmethod
    def get_time(number: int) -> bytes:
        return number.to_bytes(WireProtocol.TIME, 'big')
    

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
        
        body = socket_obj.recv(int.from_bytes(message_size, "big"))
        logger.info("Message received: {}", body)
            
        logger.info("Sending response to client")
        
        if int.from_bytes(api_key, "big") == 18 and int.from_bytes(api_version, "big") <= 4: # ApiVersions
            socket_obj.send(WireProtocol.message_size(19)) # Message size, need to add calculation logic
            socket_obj.send(correlation_id)  # Correlation Id
            socket_obj.send(Errors.NO_ERROR.to_bytes(2, 'big')) # Error
            socket_obj.send(WireProtocol.get_api_key_array_length(2))
            socket_obj.send(api_key)
            socket_obj.send(WireProtocol.get_request_api_key(0)) # Min version
            socket_obj.send(WireProtocol.get_request_api_key(4)) # Max version
            socket_obj.send(WireProtocol.get_buffer(0))
            socket_obj.send(WireProtocol.get_time(0))
            socket_obj.send(WireProtocol.get_buffer(0))    
        else:
            socket_obj.send(WireProtocol.message_size(6)) # Message size
            socket_obj.send(correlation_id)
            # 2 bytes is the size for the error 
            socket_obj.send(Errors.UNSUPPORTED_VERSION.to_bytes(2, 'big'))
        socket_obj.close()
        logger.info("Connection to client closed")
    
    


if __name__ == "__main__":
    main()
