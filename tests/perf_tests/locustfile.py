import json

from locust import User, task, between, events
import time
from kafka import KafkaProducer


class KafkaUser(User):
    wait_time = between(0.1, 0.5)

    def on_start(self):
        self.producer = KafkaProducer(
            bootstrap_servers="localhost:9092", 
            retries=0, 
            max_block_ms=5000
        )

    def on_stop(self):
        self.producer.close()

    @task
    def produce_message(self):
        message = json.dumps({"key": "value", "timestamp": time.time()}).encode("utf-8")

        start_time = time.perf_counter()
        exception = None

        try:
            self.producer.send("grape", message)
        except Exception as e:
            exception = e
        finally:
            elapsed = (time.perf_counter() - start_time) * 1000  # ms

            # Report result to Locust's stats engine
            events.request.fire(
                request_type="kafka",
                name="produce_message",
                response_time=elapsed,
                response_length=len(str(message)),
                exception=exception,
            )