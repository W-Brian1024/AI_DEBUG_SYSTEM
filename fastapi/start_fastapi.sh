#!/bin/bash
set -e

# Load credentials from .env file
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"

if [ -f "$ENV_FILE" ]; then
    echo "[INFO] Loading credentials from $ENV_FILE"
    # Export all variables from .env file (skip comments and empty lines)
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

echo "[INFO] MinIO Access Key: ${MINIO_ACCESS_KEY:0:8}..."
echo "[INFO] MinIO Secret Key: ${MINIO_SECRET_KEY:0:8}..."

# Ensure credentials are exported for ALL subprocesses
export MINIO_ACCESS_KEY
export MINIO_SECRET_KEY

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Try to find virtual environment in multiple locations
VENV_DIRS=("$SCRIPT_DIR/fast_venv" "$SCRIPT_DIR/../ai_env" "$HOME/ai_env")

VENV_DIR=""
for dir in "${VENV_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        VENV_DIR="$dir"
        break
    fi
done

# Activate virtual environment
if [ -n "$VENV_DIR" ]; then
    echo "[INFO] Activating virtual environment: $VENV_DIR"
    source "$VENV_DIR/bin/activate"
else
    echo "[ERROR] No virtual environment found in:"
    for dir in "${VENV_DIRS[@]}"; do
        echo "  - $dir"
    done
    echo "[INFO] Please create a virtual environment first:"
    echo "  cd $SCRIPT_DIR/.. && python3 -m venv ai_env"
    echo "  source ai_env/bin/activate"
    echo "  pip install -r requirements.txt"
    exit 1
fi

# Clear proxy settings to avoid SOCKS proxy conflicts
echo "[INFO] Clearing proxy settings..."
unset ALL_PROXY all_proxy
echo "[INFO] Proxy settings cleared"

# Define log files
REDIS_LOG="redis.log"
CELERY_LOG="celery.log"
FASTAPI_LOG="fastapi.log"

# Define services
PORT=8000
SERVICES=("uvicorn" "fastapi_app" "celery" "redis-server")

# Function to cleanup duplicate processes
cleanup_processes() {
    echo "[INFO] Cleaning up duplicate processes..."

    # Clean up uvicorn and fastapi_app processes
    for service in "${SERVICES[@]}"; do
        PIDS=$(pgrep -f "$service" | grep -v grep || true)
        if [ -n "$PIDS" ]; then
            echo "[INFO] Found $service processes: $PIDS"
            echo "[INFO] Stopping $service processes..."
            pkill -f "$service" || true
            sleep 1

            # Force kill still running processes
            REMAINING_PIDS=$(pgrep -f "$service" | grep -v grep || true)
            if [ -n "$REMAINING_PIDS" ]; then
                echo "[INFO] Force killing remaining $service processes..."
                pkill -9 -f "$service" || true
            fi
            echo "[INFO] $service processes cleanup completed"
        else
            echo "[INFO] No running $service processes found"
        fi
    done

    # Clean up port occupation
    if fuser $PORT/tcp >/dev/null 2>&1; then
        echo "[INFO] Port $PORT is occupied, closing..."
        fuser -k $PORT/tcp
        sleep 2
        echo "[INFO] Port $PORT released"
    else
        echo "[INFO] Port $PORT is not occupied"
    fi
}

# Function to cleanup log files
cleanup_logs() {
    echo "[INFO] Cleaning up log files..."

    # Define log size limit (10MB)
    MAX_LOG_SIZE=10485760

    for log_file in $REDIS_LOG $CELERY_LOG $FASTAPI_LOG; do
        if [ -f "$log_file" ]; then
            LOG_SIZE=$(stat -c%s "$log_file" 2>/dev/null || echo 0)
            if [ "$LOG_SIZE" -gt "$MAX_LOG_SIZE" ]; then
                echo "[INFO] Log file $log_file size is $(($LOG_SIZE/1024/1024))MB, exceeds limit, cleaning up..."

                # Backup last 1000 lines of logs
                tail -n 1000 "$log_file" > "${log_file}.tmp"
                mv "${log_file}.tmp" "$log_file"
                echo "[INFO] Log file $log_file cleaned, keeping last 1000 lines"
            else
                echo "[INFO] Log file $log_file size is normal: $(($LOG_SIZE/1024))KB"
            fi
        fi
    done

    # Clean up old log files (keep last 5)
    for log_file in $REDIS_LOG $CELERY_LOG $FASTAPI_LOG; do
        # Find and delete old backup files
        find . -name "${log_file}.*" -type f -mtime +7 -delete 2>/dev/null || true
    done
}

# Function to check service status
check_service_status() {
    local service_name=$1
    local pid=$2
    if [ -n "$pid" ]; then
        if kill -0 $pid 2>/dev/null; then
            echo "[INFO] $service_name (PID: $pid) is running normally"
            return 0
        else
            echo "[WARNING] $service_name (PID: $pid) has stopped running"
            return 1
        fi
    else
        echo "[WARNING] $service_name PID is empty"
        return 1
    fi
}

# Main cleanup process
echo "[INFO] === Starting cleanup work before service startup ==="
cleanup_processes
cleanup_logs
echo "[INFO] === Cleanup work completed ==="
echo ""

# Check Redis service status
echo "[INFO] Checking Redis service..."
REDIS_PID=$(pgrep redis-server || true)
if [ -n "$REDIS_PID" ]; then
    echo "[INFO] Found Redis service PID: $REDIS_PID, stopping..."
    kill -15 $REDIS_PID 2>/dev/null || true
    sleep 2
    # Force kill
    if pgrep redis-server >/dev/null 2>&1; then
        pkill -9 -f redis-server || true
    fi
    echo "[INFO] Redis service has been stopped"
else
    echo "[INFO] Redis service is not running"
fi

# Start Redis service
echo "[INFO] Starting Redis..."
redis-server --daemonize yes > $REDIS_LOG 2>&1
REDIS_START_RESULT=$?

if [ $REDIS_START_RESULT -ne 0 ]; then
    echo "[ERROR] Redis startup failed, return code: $REDIS_START_RESULT"
    echo "[ERROR] Please check logs: tail -n 20 $REDIS_LOG"
    exit 1
fi

# Wait for Redis to fully start and verify
sleep 3
REDIS_NEW_PID=$(pgrep redis-server || true)
if [ -n "$REDIS_NEW_PID" ]; then
    echo "[INFO] Redis started successfully, PID: $REDIS_NEW_PID"
    # Test Redis connection
    if redis-cli ping > /dev/null 2>&1; then
        echo "[INFO] Redis connection test passed"
    else
        echo "[WARNING] Redis connection test failed, but process has started"
    fi
else
    echo "[ERROR] Redis startup failed, process not found"
    echo "[ERROR] Please check logs: tail -n 20 $REDIS_LOG"
    exit 1
fi

# Wait for services to fully start
sleep 2

# Start Celery Worker
echo "[INFO] Starting Celery Worker..."
# Re-export MinIO credentials to ensure they are available after venv activation
export MINIO_ACCESS_KEY
export MINIO_SECRET_KEY
CELERY_PID=""
POOL_TYPES=("solo" "prefork" "gevent" "eventlet")

for POOL_TYPE in "${POOL_TYPES[@]}"; do
    echo "[INFO] Trying pool type: $POOL_TYPE"

    # Clean up previous celery processes
    pkill -f "celery worker" 2>/dev/null || true
    sleep 1

    python -m celery -A celery_app worker --loglevel=info --pool=$POOL_TYPE --concurrency=4 > $CELERY_LOG 2>&1 &
    CELERY_PID=$!

    # Wait for process to start
    sleep 5

    if kill -0 $CELERY_PID 2>/dev/null; then
        # Check if celery is actually working
        if python -m celery -A celery_app inspect ping > /dev/null 2>&1; then
            echo "[INFO] Celery Worker started successfully, PID: $CELERY_PID, pool type: $POOL_TYPE"
            break
        else
            echo "[WARNING] Celery Worker process exists but not responding, trying next pool type..."
            pkill -9 -f "celery worker" 2>/dev/null || true
        fi
    else
        echo "[WARNING] Pool type $POOL_TYPE startup failed, trying next..."
    fi

    CELERY_PID=""
done

if [ -z "$CELERY_PID" ]; then
    echo "[ERROR] All pool types failed, Celery Worker cannot be started"
    echo "[ERROR] Please check logs: tail -n 20 $CELERY_LOG"
    exit 1
fi

# Wait for Celery to fully start
sleep 3

# Start FastAPI service
echo "[INFO] Starting FastAPI service (Uvicorn)..."
# Export MinIO credentials for subprocesses
export MINIO_ACCESS_KEY
export MINIO_SECRET_KEY

python fastapi_app.py > $FASTAPI_LOG 2>&1 &
FASTAPI_PID=$!
FASTAPI_START_RESULT=$?

if [ $FASTAPI_START_RESULT -ne 0 ]; then
    echo "[ERROR] FastAPI startup failed, return code: $FASTAPI_START_RESULT"
    echo "[ERROR] Please check logs: tail -n 20 $FASTAPI_LOG"
    # Clean up started services
    kill $CELERY_PID 2>/dev/null || true
    redis-cli shutdown 2>/dev/null || true
    exit 1
fi

# Verify FastAPI process is running
sleep 3
if ! kill -0 $FASTAPI_PID 2>/dev/null; then
    echo "[ERROR] FastAPI process exited abnormally after startup"
    echo "[ERROR] Please check logs: tail -n 20 $FASTAPI_LOG"
    # Clean up started services
    kill $CELERY_PID 2>/dev/null || true
    redis-cli shutdown 2>/dev/null || true
    exit 1
fi

echo "[INFO] FastAPI service has been started, PID: $FASTAPI_PID"
echo "[INFO] Access URL: http://localhost:$PORT"

# Health check
echo "[INFO] Waiting for services to start, performing health check..."
HEALTH_CHECK_ATTEMPTS=0
MAX_ATTEMPTS=10

while [ $HEALTH_CHECK_ATTEMPTS -lt $MAX_ATTEMPTS ]; do
    sleep 2
    HEALTH_CHECK_ATTEMPTS=$((HEALTH_CHECK_ATTEMPTS + 1))

    # Check FastAPI health status
    if curl -s -f http://localhost:$PORT/health > /dev/null 2>&1; then
        echo "[INFO] FastAPI health check passed (attempt: $HEALTH_CHECK_ATTEMPTS)"
        HEALTH_CHECK_PASSED=true
        break
    else
        echo "[INFO] FastAPI health check failed (attempt $HEALTH_CHECK_ATTEMPTS/$MAX_ATTEMPTS)"

        # Check if process is still running
        if ! kill -0 $FASTAPI_PID 2>/dev/null; then
            echo "[ERROR] FastAPI process has stopped running"
            break
        fi
    fi
done

if [ "$HEALTH_CHECK_PASSED" != "true" ]; then
    echo "[ERROR] FastAPI health check ultimately failed"
    echo "[ERROR] Please check logs: tail -n 20 $FASTAPI_LOG"
    # Clean up started services
    kill $CELERY_PID 2>/dev/null || true
    redis-cli shutdown 2>/dev/null || true
    exit 1
fi

# Final service status check
echo ""
echo "[INFO] === Final service status check ==="
check_service_status "Redis" $REDIS_NEW_PID
check_service_status "Celery" $CELERY_PID
check_service_status "FastAPI" $FASTAPI_PID

# Display service information
echo ""
echo "[INFO] === Service startup completed ==="
echo "  - FastAPI: http://localhost:$PORT"
echo "  - FastAPI PID: $FASTAPI_PID"
echo "  - Celery PID: $CELERY_PID"
echo "  - Celery pool type: $POOL_TYPE"
echo "  - Redis PID: $REDIS_NEW_PID"
echo ""
echo "  - Redis log: $REDIS_LOG"
echo "  - Celery log: $CELERY_LOG"
echo "  - FastAPI log: $FASTAPI_LOG"
echo ""

# Add management commands
echo "[INFO] === Service management commands ==="
echo "  - Stop all services: kill $FASTAPI_PID $CELERY_PID && redis-cli shutdown"
echo "  - Check process status: ps aux | grep -E '(uvicorn|celery|redis)'"
echo "  - View logs: tail -f $FASTAPI_LOG"
echo "  - Health check: curl http://localhost:$PORT/health"
echo ""

# Save PIDs to files for management
echo $FASTAPI_PID > fastapi.pid
echo $CELERY_PID > celery.pid
echo $REDIS_NEW_PID > redis.pid
echo "[INFO] PID files saved: fastapi.pid, celery.pid, redis.pid"

# Display startup time
echo "[INFO] Startup completion time: $(date '+%Y-%m-%d %H:%M:%S')"
echo "[INFO] All services have been successfully started and are running"