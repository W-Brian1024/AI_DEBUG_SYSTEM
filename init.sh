#!/bin/bash
# Initialization script for ESP32 AI Debug System
# This script initializes and starts all required services



echo ""
echo "=========================================="
echo "ESP32 AI Debug System - Initialization"
echo "=========================================="
echo ""

# ============================
# 1. Check Environment
# ============================
echo "[1/4] Checking environment..."
echo ""

# Check Python3
if ! command -v python3 &> /dev/null; then
    echo "✗ Python3 not found. Please install: sudo apt install python3"
    echo ""
    exit 1
else
    echo "✓ Python3: $(python3 --version)"
    echo ""
fi

# Check pip3
if ! command -v pip3 &> /dev/null; then
    echo "✗ pip3 not found. Please install: sudo apt install python3-pip"
    echo ""
    exit 1
else
    echo "✓ pip3 found"
    echo ""
fi

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "✗ Docker not found. Please install Docker first"
    echo ""
    exit 1
else
    echo "✓ Docker: $(docker --version)"
    echo ""
fi

# Check Redis
if ! command -v redis-server &> /dev/null; then
    echo "✗ Redis not found. Please install: sudo apt install redis-server"
    echo ""
    exit 1
else
    echo "✓ Redis found"
    echo ""
fi

# ============================
# 2. Setup .env file
# ============================
echo ""
echo "[2/4] Setting up .env file..."
echo ""

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "✓ Created .env file"
    echo ""
    echo "  Please edit .env and add your ZHIPU_API_KEY"
    echo ""
else
    echo "✓ .env file already exists"
    echo ""
fi

# ============================
# 3. Setup MinIO
# ============================
echo ""
echo "[3/4] Setting up MinIO..."
echo ""

if [ -f "docker/setup_docker.sh" ]; then
    bash docker/setup_docker.sh
    echo "✓ MinIO setup completed"
    echo ""
else
    echo "✗ docker/setup_docker.sh not found"
    echo ""
    exit 1
fi

# ============================
# 4. Validate Configuration
# ============================
echo ""
echo "[4/4] Validating configuration..."
echo ""
python3 check_config/check_config.py

if [ $? -eq 0 ]; then
    echo "Configuration valid"
    echo ""
else
    echo "Configuration validation failed (may need API keys in .env)"
    echo ""
fi

# ============================
# Done
# ============================
echo ""
echo "=========================================="
echo ""
echo "✓ Initialization completed!"
echo ""
echo "=========================================="
echo ""
echo "Next steps:"
echo ""
echo "  1. Edit .env file with your API keys"
echo ""
echo "  2. cd fastapi && ./start_fastapi.sh"
echo ""
echo "  3. ./esp32_catch/flash_auto.sh /dev/ttyUSB0"
echo ""