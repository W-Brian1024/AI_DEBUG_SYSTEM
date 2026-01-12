#!/bin/bash
# Deinitialization script for ESP32 AI Debug System
# This script stops all running services and cleans up resources

# Don't use set -e to avoid hanging on failures

echo "=========================================="
echo "ESP32 AI Debug System - Cleanup"
echo "=========================================="
echo ""

# Get project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[CLEANUP] Stopping all services..."
echo ""

# Stop FastAPI and Celery processes
echo "Stopping FastAPI and Celery processes..."
PIDS=$(pgrep -f "(uvicorn|fastapi_app|celery worker)" 2>/dev/null || true)
if [ -n "$PIDS" ]; then
    echo "Found: $PIDS"
    echo "$PIDS" | xargs -r kill -15 >/dev/null 2>&1 || true
    REMAINING=$(pgrep -f "(uvicorn|fastapi_app|celery worker)" 2>/dev/null || true)
    if [ -n "$REMAINING" ]; then
        echo "$REMAINING" | xargs -r kill -9 >/dev/null 2>&1 || true
    fi
    echo "Stopped"
    echo ""
else
    echo "None running"
    echo ""
fi

# Stop Redis
echo "Stopping Redis service..."
echo ""
REDIS_PID=$(pgrep redis-server 2>/dev/null || true)
if [ -n "$REDIS_PID" ]; then
    echo "Found PID: $REDIS_PID"
    echo ""
    {
        kill -15 $REDIS_PID 2>/dev/null || sudo kill -15 $REDIS_PID 2>/dev/null || true
    } >/dev/null 2>&1
    if pgrep redis-server >/dev/null 2>&1; then
        {
            pkill -9 -f redis-server 2>/dev/null || sudo pkill -9 -f redis-server 2>/dev/null || true
        } >/dev/null 2>&1
    fi
    echo "Stopped"
    echo ""
else
    echo "Not running"
    echo ""
fi

# Stop MinIO Docker container
echo "Stopping MinIO container..."
echo ""
DOCKER_RUNNING=false
if docker ps >/dev/null 2>&1; then
    DOCKER_RUNNING=true
    DOCKER_CMD="docker"
elif sudo docker ps >/dev/null 2>&1; then
    DOCKER_RUNNING=true
    DOCKER_CMD="sudo docker"
fi

if [ "$DOCKER_RUNNING" = true ]; then
    if $DOCKER_CMD ps --format "{{.Names}}" 2>/dev/null | grep -Eq "^minio$" 2>/dev/null; then
        $DOCKER_CMD stop minio >/dev/null 2>&1 || true
        echo "Stopped"
        echo ""
    else
        echo "Not running"
        echo ""
    fi
else
    echo "Docker not accessible, skipped"
    echo ""
fi

# Stop log capture scripts
echo "Stopping log capture scripts..."
echo ""
CAPTURE_PIDS=$(pgrep -f "catch_logs_auto.sh" 2>/dev/null || true)
if [ -n "$CAPTURE_PIDS" ]; then
    echo "$CAPTURE_PIDS" | xargs -r kill -9 >/dev/null 2>&1 || true
    echo "Stopped"
    echo ""
else
    echo "None running"
    echo ""
fi

# Release ports
echo "Releasing occupied ports..."
echo ""
for PORT in 8000 6379 9000 9001; do
    fuser -k ${PORT}/tcp >/dev/null 2>&1 || true
done
echo "Ports released"
echo ""

# Clean up PID files
echo "Cleaning up PID files..."
echo ""
find "$SCRIPT_DIR" -name "*.pid" -type f -delete 2>/dev/null || true

echo ""
echo "=========================================="
echo ""
echo "Cleanup completed!"
echo ""
echo "=========================================="
echo ""

# Ensure script exits properly
exit 0
