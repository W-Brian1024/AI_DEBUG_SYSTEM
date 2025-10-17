#!/bin/bash
set -e

CONTAINER_NAME="minio"

# Usage information
usage() {
    echo "Usage: $0 <ttyUSBx> [MINIO_ACCESS_KEY] [MINIO_SECRET_KEY]"
    echo "Example: $0 /dev/ttyUSB0"
    echo "Example: $0 /dev/ttyUSB0 your-access-key your-secret-key"
    exit 1
}

# Check if serial port parameter is provided
if [ $# -lt 1 ]; then
    usage
fi

# Set variables
PORT=$1
MINIO_ACCESS_KEY=${2:-"minioadmin"}
MINIO_SECRET_KEY=${3:-"minioadmin"}
CATCH_SCRIPT="./catch_logs_auto.sh"

# Export MinIO credentials for subprocesses
export MINIO_ACCESS_KEY
export MINIO_SECRET_KEY

echo "[INFO] MinIO credentials configured:"
echo "[INFO]  Access Key: ${MINIO_ACCESS_KEY:0:8}..."
echo "[INFO]  Secret Key: ${MINIO_SECRET_KEY:0:8}..."

# check the docker is running
if sudo docker ps --filter "name=$CONTAINER_NAME" --filter "status=running" | grep -q "$CONTAINER_NAME"; then
    echo "[INFO] MinIO ($CONTAINER_NAME) is already running, skipping."
else
    echo "[INFO] MinIO is not running, starting..."
    sudo docker start $CONTAINER_NAME
fi

if [ $# -lt 1 ]; then
    echo "Usage: $0 <ttyUSBx>"
    exit 1
fi

PORT=$1
CATCH_SCRIPT="./catch_logs_auto.sh"

# 1. Check if catch_logs_auto.sh is running
PID=$(pgrep -f "catch_logs_auto.sh $PORT" || true)

if [ -n "$PID" ]; then
    echo "[INFO] Found catch_logs_auto.sh running on $PORT (PID: $PID), killing..."
    kill -9 $PID
    sleep 1
else
    echo "[INFO] No catch_logs_auto.sh running for $PORT"
fi

# 2. Execute flash
echo "[INFO] Flashing ESP32 on $PORT..."
idf.py flash -p $PORT

# 3. After flash completes, re-run catch_logs_auto.sh
if [ -f "$CATCH_SCRIPT" ]; then
    echo "[INFO] Running $CATCH_SCRIPT with $PORT..."
    $CATCH_SCRIPT $PORT
else
    echo "[WARN] $CATCH_SCRIPT not found, skip running."
fi

