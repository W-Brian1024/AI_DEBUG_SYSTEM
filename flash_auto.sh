#!/bin/bash
set -e

CONTAINER_NAME="minio"

# Load credentials from .env file
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    echo "[INFO] Loading credentials from $ENV_FILE"
    # Export all variables from .env file
    set -a
    source "$ENV_FILE"
    set +a
    echo "[INFO] Loaded $(grep -c '^[^#]' "$ENV_FILE") variables from .env"
else
    echo "[WARNING] .env file not found at $ENV_FILE"
    echo "[INFO] Using default credentials (minioadmin/minioadmin)"
    export MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-minioadmin}"
    export MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-minioadmin}"
fi

# Usage information
usage() {
    echo "Usage: $0 <ttyUSBx> [MINIO_ACCESS_KEY] [MINIO_SECRET_KEY]"
    echo "Example: $0 /dev/ttyUSB0"
    echo "Example: $0 /dev/ttyUSB0 your-access-key your-secret-key"
    echo "[INFO] Credentials are loaded from .env file by default"
    exit 1
}

# Check if serial port parameter is provided
if [ $# -lt 1 ]; then
    usage
fi

# Set variables
PORT=$1
# Allow command line arguments to override .env values (for backwards compatibility)
MINIO_ACCESS_KEY=${2:-$MINIO_ACCESS_KEY}
MINIO_SECRET_KEY=${3:-$MINIO_SECRET_KEY}
CATCH_SCRIPT="$SCRIPT_DIR/esp32_catch/catch_logs_auto.sh"

# Export MinIO credentials for subprocesses
export MINIO_ACCESS_KEY
export MINIO_SECRET_KEY

echo "[INFO] MinIO credentials configured:"
echo "[INFO]  Access Key: ${MINIO_ACCESS_KEY:0:8}..."
echo "[INFO]  Secret Key: ${MINIO_SECRET_KEY:0:8}..."

# Check if user can run Docker (with or without sudo)
check_docker_command() {
    if docker ps --format "table {{.Names}}" &> /dev/null; then
        echo "docker"
        return 0
    elif sudo docker ps --format "table {{.Names}}" &> /dev/null; then
        echo "sudo docker"
        return 0
    else
        echo "failed"
        return 1
    fi
}

# Simple check if MinIO container is available
DOCKER_CMD=$(check_docker_command)

if [ "$DOCKER_CMD" = "failed" ]; then
    echo "[WARN] Cannot access Docker. Please check Docker installation or permissions"
    echo "[INFO] If Docker is installed, you may need to:"
    echo "  1. Add user to docker group: sudo usermod -aG docker \$USER"
    echo "  2. Log out and log back in, or run: newgrp docker"
    echo "  3. Or run: ./setup_docker.sh"
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
elif $DOCKER_CMD ps --format "table {{.Names}}" | grep -q "$CONTAINER_NAME"; then
    echo "[INFO] MinIO container is running"
else
    echo "[WARN] MinIO container '$CONTAINER_NAME' is not running"
    echo "[INFO] Please run ./setup_docker.sh first to set up MinIO"
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# PORT and CATCH_SCRIPT are already set above, no need to duplicate

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

