# Kafka clone

This implementation is based on the ["Build Your Own Kafka" Challenge](https://codecrafters.io/challenges/kafka) and goes beyond it. Still under construction.


# Installation
- Ensure you have `uv` installed locally 
- Execute `uv sync`
- Execute `uv run python -m app.main --config config/local.json` to run the implementation locally


# Generate/edit metadata
`tools/create_cluster_metadata.py` generates a minimal KRaft cluster metadata log file that registers one or more topics so our broker can serve Metadata and Produce requests for them.

The output path is read from a config file (same format used by app.main),
defaulting to config/local.json. Pass --config to target a different environment.

Usage:
```bash
uv run tools/create_cluster_metadata.py --topic grape --partitions 2
uv run tools/create_cluster_metadata.py --topic grape --partitions 2 --topic pear --partitions 1
uv run tools/create_cluster_metadata.py --config config/docker.json --topic foo
uv run tools/create_cluster_metadata.py --output /tmp/my-cluster/meta.log --topic foo
uv run tools/create_cluster_metadata.py --config config/docker.json --topic foo --append
```

# Running with Docker

The easiest way is with Docker Compose, which encodes the resource limits and
volume configuration so you don't need to remember `docker run` flags:

```bash
docker compose up --build
```

This starts the broker with:
- Port 9092 forwarded to `localhost:9092`
- Data persisted in a named volume (`kafka-data`)
- CPU capped at 1 core and memory at 256 MB (useful for performance testing)

To use a local directory for data instead of the named volume:
```bash
KAFKA_DATA_DIR=/absolute/path/to/data docker compose up --build
```

To confirm the limits are in effect while the container is running:
```bash
docker stats
```

### Manual docker run (alternative)

Build the image:
```
docker build -t kafka-broker .
```

Run the broker (data is persisted in a named volume):
```
docker run -p 9092:9092 -v kafka-data:/data kafka-broker
```

To use your own local data directory instead of a named volume:
```
docker run -p 9092:9092 -v /absolute/path/to/data:/data kafka-broker
```

The broker listens on port 9092. Connect clients to `localhost:9092` as usual.

# Testing
To run the tests localy:
```
uv run pytest --cov=. --cov-report=html
```
These tests will create a html directory with a coverage report.

# Performance tests
To run the performance test
```
uv run --project tests/perf_tests locust --processes 4 -f tests/perf_tests/locustfile.py
```

# Benchmarks
Benchmarks are on a very initail stage.
The script `./tools/start.sh` will delete the old corresponding metadata, create new files, run the broker and the consumer.
Usage:
```bash
# defaults: topic=grape, partitions=2, config=config/local.json
./tools/start.sh

# custom
./tools/start.sh grape 4
./tools/start.sh grape 4 config/docker.json
```


`/benchmarks/producer_by_partitions.png` contains a serie of tests using 100 concurrent users with different number of corresponding partitions (1, 2, 5 and 10). The test is done on MacBook Pro M1 with 16GB of memory without any specific limitations.