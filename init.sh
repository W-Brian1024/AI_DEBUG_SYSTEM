#!/bin/bash
# Simple initialization script for ESP32 AI Debug System

echo "[INFO] Initializing ESP32 AI Debug System..."

# 1. Setup .env file
if [ ! -f ".env" ]; then
    echo "[INFO] Creating .env file..."
    cp .env.example .env
    echo "[INFO] Please edit .env file and add your ZhiPu API key"
else
    echo "[INFO] .env file already exists"
fi

# 2. Validate configuration
echo "[INFO] Validating configuration..."
python3 check_config/check_config.py

# 3. Setup MinIO
echo "[INFO] Setting up MinIO..."
./setup_docker.sh

echo "[INFO] Initialization completed!"
echo "[INFO] Next steps:"
echo "  1. Edit .env file with your API keys"
echo "  2. cd fastapi && ./start_fastapi.sh"
echo "  3. ./flash_auto.sh /dev/ttyUSB0"