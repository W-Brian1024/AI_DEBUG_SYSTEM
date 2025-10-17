# ESP32 AI Debug System

An intelligent ESP32 log analysis system powered by AI that automatically captures, processes, and analyzes ESP32 logs to provide actionable insights and problem diagnosis.

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- Docker & Docker Compose
- ESP-IDF (for ESP32 development)
- Redis
- MinIO (S3-compatible object storage)

### 1. Environment Setup

#### Clone the Repository
```bash
git clone <repository-url>
```

#### Python Virtual Environment
```bash
cd fastapi
python3 -m venv fast_venv
source fast_venv/bin/activate  # On Windows: fast_venv\Scripts\activate
pip install -r requirements.txt
```

#### MinIO Setup
```bash
# Option 1: Using Docker (Recommended)
docker run -d \
  --name minio \
  -p 9000:9000 -p 9001:9001 \
  --restart unless-stopped \
  -v $(pwd)/minio-data:/data \
  -e "MINIO_ROOT_USER=minioadmin" \
  -e "MINIO_ROOT_PASSWORD=minioadmin" \
  minio/minio server /data --console-address ":9001"

# Option 2: Local Installation
# Download and install MinIO from https://min.io/download
```

#### Redis Setup
```bash
# Using Docker
docker run -d --name redis -p 6379:6379 redis:alpine

# Or install locally
sudo apt-get install redis-server  # Ubuntu/Debian
brew install redis  # macOS
```

### 2. Configuration

#### MinIO Credentials
Create a MinIO bucket and get your access keys:
1. Open http://localhost:9001
2. Login with `minioadmin` / `minioadmin`
3. Create a bucket named `ble1`
4. Generate access keys in Users section

#### Environment Variables
```bash
# Create .env file
cat > .env << EOF
MINIO_ACCESS_KEY=your-access-key-here
MINIO_SECRET_KEY=your-secret-key-here
DEEPSEEK_API_KEY=your-deepseek-api-key-here
EOF

# Or set in shell
export MINIO_ACCESS_KEY="your-access-key"
export MINIO_SECRET_KEY="your-secret-key"
export DEEPSEEK_API_KEY="your-deepseek-api-key"
```

### 3. Start Services

#### Using the Startup Script (Recommended)
```bash
cd fastapi
chmod +x start_fastapi.sh
./start_fastapi.sh
```

#### Manual Startup
```bash
# Terminal 1: Start Redis
redis-server

# Terminal 2: Start Celery Worker
cd fastapi
source fast_venv/bin/activate
celery -A celery_app worker --loglevel=info

# Terminal 3: Start FastAPI
cd fastapi
source fast_venv/bin/activate
python -m uvicorn fastapi_app:app --reload --host 0.0.0.0 --port 8000
```

### 4. Verify Installation

Open http://localhost:8000 in your browser to access the web interface.

## 📋 Usage Guide

### ESP32 Log Capture

#### Method 1: One-Click Flash & Capture (Recommended)
```bash
# Basic usage (default MinIO credentials)
./flash_auto.sh /dev/ttyUSB0

# With custom MinIO credentials
./flash_auto.sh /dev/ttyUSB0 your-access-key your-secret-key
```

### Web Interface Usage

1. **Upload Files**: Access http://localhost:8000 and upload log files
2. **Monitor Progress**: Real-time processing status updates
3. **View Analysis**: AI-powered analysis results and recommendations
4. **Interactive Q&A**: Ask questions about your logs

### API Usage

#### Upload Log Files
```bash
curl -X POST "http://localhost:8000/upload/" \
  -F "file=@your_log_file.txt" \
  -F 'metadata={"device": "ESP32", "firmware": "v1.0"}'
```

#### Check Task Status
```bash
curl "http://localhost:8000/status/{event_id}"
```

#### Ask Questions
```bash
curl -X POST "http://localhost:8000/ask/" \
  -H "Content-Type: application/json" \
  -d '{"event_id": "your-event-id", "question": "What caused this error?"}'
```

## 🏗️ System Architecture

```
ESP32 Device
    │
    ▼
Log Capture Scripts
    │
    ▼
FastAPI Server (Port 8000)
    │
    ▼
Object Storage (MinIO)
    │
    ▼
Celery Workers + Redis Queue
    │
    ▼
LLM Analysis Engine (DeepSeek)
    │
    ▼
Web Interface + API
```

## 📁 Project Structure

```
esp_ai_debug/
├── fastapi/                    # Backend services
│   ├── fastapi_app.py         # FastAPI main application
│   ├── celery_app.py          # Celery background tasks
│   ├── start_fastapi.sh       # Service startup script
│   └── requirements.txt       # Python dependencies
├── catch_esp_log.py           # ESP32 log capture script
├── catch_logs_auto.sh         # Automated log capture
├── flash_auto.sh              # Flash + capture script
├── log_monitor.py             # Directory monitoring
├── logs/                      # Local log storage
└── README.md                  # This file
```

## ⚙️ Configuration Options

### MinIO Configuration
Edit `fastapi_app.py` and `celery_app.py`:
```python
minio_client = Minio(
    endpoint="localhost:9000",
    access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
    secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
    secure=False
)
```

### API Keys
Set your DeepSeek API key:
```bash
export DEEPSEEK_API_KEY="your-api-key"
```

### Log File Paths
- **Relative paths** are used for portability
- Default log directory: `./logs`
- Default virtual serial: `/tmp/ttyVLOG`

## 🔧 Troubleshooting

### Common Issues

#### 1. MinIO Connection Failed
```bash
# Check MinIO status
docker ps | grep minio

# Restart MinIO
docker restart minio

# Check credentials
curl -X GET "http://localhost:9000/minio/health/live"
```

#### 2. Celery Worker Not Starting
```bash
# Check Redis
redis-cli ping

# Restart services
./start_fastapi.sh
```

#### 3. Virtual Serial Port Issues
```bash
# Check permissions
ls -la /tmp/ttyVLOG

# Create virtual serial port
sudo socat -d -d /dev/ttyUSB0,raw,echo=0,b115200 PTY,link=/tmp/ttyVLOG,raw,echo=0,b115200 &
```

#### 4. Port Conflicts
```bash
# Check port usage
netstat -tulpn | grep :8000
netstat -tulpn | grep :6379
netstat -tulpn | grep :9000

# Kill processes on ports
sudo fuser -k 8000/tcp
sudo fuser -k 6379/tcp
sudo fuser -k 9000/tcp
```

### Debug Mode

Enable debug logging:
```bash
# FastAPI debug mode
python -m uvicorn fastapi_app:app --reload --host 0.0.0.0 --port 8000 --log-level debug

# Celery debug mode
celery -A celery_app worker --loglevel=debug
```

For issues and questions:
- Create an issue on GitHub
- Check the troubleshooting section
- Review the system architecture documentation

---

**Note**: This system is designed for ESP32 BLE debugging but can be adapted for other embedded systems with minimal configuration changes.