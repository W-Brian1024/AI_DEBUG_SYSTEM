#!/bin/bash
set -e

# ============================
# Load configuration from .env file
# ============================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Try root .env first, fallback to docker/.env
if [ -f "$PROJECT_ROOT/.env" ]; then
    ENV_FILE="$PROJECT_ROOT/.env"
    echo "[INFO] Loading credentials from $ENV_FILE"
elif [ -f "$SCRIPT_DIR/.env" ]; then
    ENV_FILE="$SCRIPT_DIR/.env"
    echo "[INFO] Loading credentials from $ENV_FILE"
else
    ENV_FILE=""
    echo "[WARNING] .env file not found at $PROJECT_ROOT/.env or $SCRIPT_DIR/.env"
    echo "[INFO] Using default credentials (minioadmin/minioadmin)"
    export MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-minioadmin}"
    export MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-minioadmin}"
fi

if [ -n "$ENV_FILE" ]; then
    # Export all variables from .env file
    set -a
    source "$ENV_FILE"
    set +a
    echo "[INFO] Loaded $(grep -c '^[^#]' "$ENV_FILE") variables from .env"
fi

# Allow command line arguments to override .env values (for backwards compatibility)
MINIO_ACCESS_KEY=${1:-$MINIO_ACCESS_KEY}
MINIO_SECRET_KEY=${2:-$MINIO_SECRET_KEY}

CONTAINER_NAME=minio
DATA_DIR=$HOME/minio-data
MINIO_PORT=9000
MINIO_CONSOLE_PORT=9001

# ============================
# Check if Docker is installed
# ============================
if ! command -v docker &> /dev/null; then
    echo "Docker is not installed. Installing..."
    
    sudo apt update
    sudo apt install -y ca-certificates curl gnupg lsb-release

    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt update
    sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    sudo groupadd docker 2>/dev/null || true
    sudo usermod -aG docker $USER

    echo "Docker installation completed. Please log out and log back in, or run 'newgrp docker' to activate permissions."
    echo "Then re-run this script."
    exit 0
fi

# ============================
# Check Docker service
# ============================
if ! sudo systemctl is-active --quiet docker; then
    echo "Docker service is not running. Starting Docker..."
    sudo systemctl start docker
    sudo systemctl enable docker
fi

# ============================
# Ensure current user is in the docker group
# ============================
if ! groups $USER | grep -q docker; then
    echo "⚠️ Current user is not in the docker group. Please run:"
    echo "  sudo usermod -aG docker $USER && newgrp docker"
    exit 1
fi

# ============================
# Create data directory
# ============================
mkdir -p $DATA_DIR

# ============================
# Check Docker command availability
# ============================
DOCKER_CMD="docker"
if ! docker ps >/dev/null 2>&1; then
    if sudo docker ps >/dev/null 2>&1; then
        DOCKER_CMD="sudo docker"
    else
        echo "ERROR: Cannot access Docker. Please check Docker installation or permissions."
        exit 1
    fi
fi

# ============================
# Pull MinIO image
# ============================
echo "Pulling MinIO image..."
$DOCKER_CMD pull minio/minio:latest

# ============================
# Stop and remove existing container if exists
# ============================
if $DOCKER_CMD ps -a --format '{{.Names}}' | grep -Eq "^${CONTAINER_NAME}\$"; then
    echo "Stopping and removing existing container $CONTAINER_NAME..."
    $DOCKER_CMD stop $CONTAINER_NAME
    $DOCKER_CMD rm $CONTAINER_NAME
fi

# ============================
# Run MinIO container
# ============================
echo "Creating and starting MinIO container..."
$DOCKER_CMD run -d \
  --name $CONTAINER_NAME \
  -p ${MINIO_PORT}:9000 \
  -p ${MINIO_CONSOLE_PORT}:9001 \
  -e "MINIO_ROOT_USER=$MINIO_ACCESS_KEY" \
  -e "MINIO_ROOT_PASSWORD=$MINIO_SECRET_KEY" \
  -v $DATA_DIR:/data \
  --restart=always \
  minio/minio server /data --console-address ":9001"

echo "✅ MinIO container is running!"
echo "Web console: http://localhost:$MINIO_CONSOLE_PORT"
echo "Username: $MINIO_ACCESS_KEY"
echo "Password: $MINIO_SECRET_KEY"
