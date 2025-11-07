#!/bin/bash
set -e

# ============================
# Default configuration (can be overridden by arguments)
# ============================
# First argument: MINIO_ACCESS_KEY, default "minioadmin"
MINIO_ACCESS_KEY=${1:-minioadmin}

# Second argument: MINIO_SECRET_KEY, default "minioadmin"
MINIO_SECRET_KEY=${2:-minioadmin}

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
# Pull MinIO image
# ============================
echo "Pulling MinIO image..."
docker pull minio/minio:latest

# ============================
# Stop and remove existing container if exists
# ============================
if docker ps -a --format '{{.Names}}' | grep -Eq "^${CONTAINER_NAME}\$"; then
    echo "Stopping and removing existing container $CONTAINER_NAME..."
    docker stop $CONTAINER_NAME
    docker rm $CONTAINER_NAME
fi

# ============================
# Run MinIO container
# ============================
echo "Creating and starting MinIO container..."
docker run -d \
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
