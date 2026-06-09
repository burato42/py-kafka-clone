#!/usr/bin/env bash
set -euo pipefail

TOPIC="${1:-grape}"
PARTITIONS="${2:-2}"
CONFIG="${3:-config/local.json}"

DATA_DIR=$(python3 -c "import json; print(json.load(open('$CONFIG'))['partition_log_dir'])")

echo "==> Cleaning data for topic '$TOPIC' ($PARTITIONS partitions) in $DATA_DIR"
rm -rf "$DATA_DIR/__cluster_metadata-0/00000000000000000000.log"
for i in $(seq 0 $((PARTITIONS - 1))); do
    rm -rf "$DATA_DIR/${TOPIC}-${i}"
done

echo "==> Creating cluster metadata"
uv run tools/create_cluster_metadata.py --config "$CONFIG" --topic "$TOPIC" --partitions "$PARTITIONS"

echo "==> Starting broker (config: $CONFIG)"
uv run -m app.main --config "$CONFIG" &
BROKER_PID=$!
trap "kill $BROKER_PID 2>/dev/null" EXIT

echo "==> Waiting for broker to be ready..."
for i in $(seq 1 20); do
    if lsof -i :9092 -sTCP:LISTEN -n -P &>/dev/null; then
        echo "    Broker is up (pid $BROKER_PID)"
        break
    fi
    sleep 0.5
done

echo "==> Starting consumer (topic: $TOPIC)"
uv run tools/consumer.py
