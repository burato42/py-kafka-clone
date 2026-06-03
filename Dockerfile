FROM python:3.14-rc-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev

COPY app/ ./app/
COPY config/ ./config/

VOLUME ["/data"]

EXPOSE 9092

CMD ["uv", "run", "--no-sync", "-m", "app.main", "--config", "config/docker.json"]
