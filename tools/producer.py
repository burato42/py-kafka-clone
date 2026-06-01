from kafka import KafkaProducer
from kafka.errors import KafkaTimeoutError

producer = KafkaProducer(bootstrap_servers="localhost:9092", retries=0, max_block_ms=5000)

for _ in range(1):
    print("Send")
    try:
        future = producer.send("grape1", b"another_message")
        result = future.get(timeout=10)
    except KafkaTimeoutError as e:
        print(f"Topic not found: {e}")
        break