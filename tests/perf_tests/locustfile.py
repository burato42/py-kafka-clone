import json

from locust import User, task, between, events
from locust.exception import StopUser
import time
from kafka import KafkaProducer


BOOTSTRAP_SERVERS = "localhost:9092"


def _calc_elapsed(start_time: float) -> float:
    return (time.perf_counter() - start_time) * 1000


def _fire(name: str, start_time: float, response_length: int = 0, exception: Exception | None = None) -> None:
    events.request.fire(
        request_type="kafka",
        name=name,
        response_time=_calc_elapsed(start_time),
        response_length=response_length,
        exception=exception,
    )


def _on_send_success(start_time: float, record_metadata) -> None:
    _fire("produce_throughput", start_time, response_length=record_metadata.serialized_value_size)


def _on_send_error(start_time: float, exc) -> None:
    _fire("produce_throughput", start_time, exception=exc)


class KafkaUser(User):
    wait_time = between(0.01, 0.05)
    producer: KafkaProducer | None = None

    def on_start(self):
        start_time = time.perf_counter()
        try:
            self.producer = KafkaProducer(bootstrap_servers=BOOTSTRAP_SERVERS, retries=0, max_block_ms=5000)
            _fire("connect", start_time)
        except Exception as e:
            _fire("connect", start_time, exception=e)
            raise StopUser() # TODO check how it behaves with a normal load without this exception

    def on_stop(self):
        if self.producer is not None:
            self.producer.close()

    @task(9)
    def produce_throughput(self):
        message = json.dumps({"key": "value", "timestamp": time.time()}).encode("utf-8")
        start_time = time.perf_counter()
        (
            self.producer.send("grape", message)
            .add_callback(_on_send_success, start_time)
            .add_errback(_on_send_error, start_time)
        )

    @task(1)
    def produce_latency(self):
        message = json.dumps({"key": "value", "timestamp": time.time()}).encode("utf-8")
        start_time = time.perf_counter()
        exception = None
        response_length = 0
        try:
            future = self.producer.send("grape", message)
            record_metadata = future.get(timeout=5)
            response_length = record_metadata.serialized_value_size
        except Exception as e:
            exception = e
        finally:
            _fire("produce_latency", start_time, response_length=response_length, exception=exception)
