from kafka import KafkaConsumer

consumer = KafkaConsumer("grape", bootstrap_servers="localhost:9092", auto_offset_reset="earliest")

for msg in consumer:
    print (msg)
