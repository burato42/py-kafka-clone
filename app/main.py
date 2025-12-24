import socket  # noqa: F401

from app.logging import logger


def main():
    print("Logs from your program will appear here!")


    server = socket.create_server(("localhost", 9092), reuse_port=True)
    server.listen()
    
    while True:
        socket_obj, details = server.accept()
        logger.info("Connection accepted...client details: {}", details)
        # 4 bytes is the size of the message in the protocol
        client_msg = socket_obj.recv(4) # TODO Probably should be 32 here
        logger.info("Message received: {}", client_msg.decode())
        
        logger.info("Sending response to client")
        msg_size = 0
        correlation_id = 7
        socket_obj.send(msg_size.to_bytes(4, 'big'))
        socket_obj.send(correlation_id.to_bytes(4, 'big'))
        socket_obj.close()
        logger.info("Connection to client closed")
    
    


if __name__ == "__main__":
    main()
