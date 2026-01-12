# ESP32 AI Debug System

AI-powered ESP32 log analysis system - automatically capture, process, and analyze logs for intelligent debugging.

## Features

- **AI Analysis**: ZhiPu AI (GLM-4.7) powered log analysis
- **Real-time Capture**: Automatic ESP32 serial log monitoring
- **Web Interface**: User-friendly dashboard at http://localhost:8000
- **Parallel Processing**: Optimized for large log files
- **Interactive Q&A**: Ask questions about your logs

## Quick Start

### 1. Prerequisites
- Python 3.8+
- Docker
- ZhiPu AI API Key

### 2. Setup (5 minutes)

```bash
# Initialize environment
cp .env.example .env
# Edit .env and add your ZHIPU_API_KEY

# Install dependencies
pip install -r fastapi/requirements.txt

# Start services
./setup_docker.sh              # MinIO
sudo docker run -d --name redis -p 6379:6379 redis:alpine  # Redis
cd fastapi && ./start_fastapi.sh  # FastAPI + Celery
```

### 3. Capture & Analyze Logs

**Option A: One-Click (Recommended)**
```bash
./flash_auto.sh /dev/ttyUSB0
```

**Option B: Manual**
```bash
# Terminal 1: Capture logs
cd esp32_catch && ./catch_logs_auto.sh /dev/ttyUSB0

# Terminal 2: Upload via web interface
open http://localhost:8000
```

## Project Structure

```
AI_DEBUG_SYSTEM/
├── fastapi/          # Backend API + Celery tasks
├── esp32_catch/      # Serial log capture scripts
├── check_config/     # Configuration management
├── config.yaml       # Central configuration
├── .env.example      # Environment variables template
└── flash_auto.sh     # One-click flash + capture
```

## Configuration

All settings in `config.yaml`:
```yaml
ai:
  provider: "zhipu"
  model: "glm-4.5"
  api_key: "${ZHIPU_API_KEY}"

server:
  host: "0.0.0.0"
  port: 8000
```

Create `.env` file:
```bash
ZHIPU_API_KEY=your-key-here
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
```

## System Architecture

```
ESP32 → Serial Capture → FastAPI → MinIO Storage
                                  ↓
                            Redis Queue
                                  ↓
                           Celery Workers
                                  ↓
                            ZhiPu AI
                                  ↓
                           Web Dashboard
```

## Common Issues

**Configuration error?**
```bash
python3 check_config/check_config.py
```

**MinIO not working?**
```bash
sudo docker restart minio
```

**Redis connection failed?**
```bash
redis-cli ping  # Should return PONG
```

**Logs not capturing?**
```bash
# Check serial port permissions
sudo usermod -aG dialout $USER
# Log out and back in
```

## API Usage

```bash
# Upload log
curl -X POST "http://localhost:8000/upload/" -F "file=@log.txt"

# Check status
curl "http://localhost:8000/status/{event_id}"

# Ask questions
curl -X POST "http://localhost:8000/ask/" \
  -H "Content-Type: application/json" \
  -d '{"event_id": "xxx", "question": "What caused the error?"}'
```

## Documentation

- [ESP32 Capture Module](esp32_catch/README.md)
- [Configuration Guide](check_config/CONFIGURATION.md)

---

**Note**: Designed for ESP32 BLE debugging but adaptable to other embedded systems.