# Kafka clone

This implementation is based on the ["Build Your Own Kafka" Challenge](https://codecrafters.io/challenges/kafka) and goes beyond it. Still under construction.


# Installation
- Ensure you have `uv` installed locally 
- Execute `uv sync`
- Execute `uv run python -m app.main --config config/local.json` to run the implementation locally


# Running with Docker

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
