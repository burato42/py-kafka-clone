# Kafka clone

This implementation is based on the ["Build Your Own Kafka" Challenge](https://codecrafters.io/challenges/kafka) and goes beyond it. Still under construction.


# Installation
- Ensure you have `uv` installed locally 
- Execute `uv sync`
- Execute `uv run python -m app.main --config config/local.json` to run the implementation locally


# Testing
To run the tests localy:
```
uv run pytest --cov=. --cov-report=html
```
These tests will create a html directory with a coverage report.
