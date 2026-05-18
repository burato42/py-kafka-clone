from kafka import KafkaProducer

producer = KafkaProducer(bootstrap_servers="localhost:9092")

for _ in range(1):
    print("Send")
    producer.send("grape", b"some_message_bytes")
