# ESP32 AI Debug System

An intelligent ESP32 log analysis system powered by AI that automatically captures, processes, and analyzes ESP32 logs to provide actionable insights and problem diagnosis.

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- Docker
- ESP-IDF (for ESP32 development)
- ZhiPu AI API Key

### 1. Environment Setup

#### Clone the Repository
```bash
git clone <repository-url>
cd AI_DEBUG_SYSTEM
```

#### Python Virtual Environment
```bash
# Use existing virtual environment or create new one
source ai_env/bin/activate

# Install dependencies
pip install -r requirements.txt
```

#### Configuration Setup
```bash
# Copy environment template
cp .env.example .env

# Edit .env file with your credentials
nano .env
```

Add your credentials to `.env`:
```bash
# MinIO Configuration
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin

# AI Service Configuration (Required!)
ZHIPU_API_KEY=your-zhipu-api-key-here
```

#### Check Configuration
```bash
# Validate all configuration
python3 check_config.py
```

### 2. Service Setup

#### Start MinIO (Object Storage)
```bash
./setup_docker.sh
```

#### Start Redis (if not using Docker setup_docker.sh)
```bash
# Option 1: Using Docker
sudo docker run -d --name redis -p 6379:6379 redis:alpine --restart unless-stopped

# Option 2: System package
sudo apt install redis-server
sudo systemctl start redis
```

### 3. Start the Application

#### Automated Startup (Recommended)
```bash
cd fastapi
./start_fastapi.sh
```

#### Manual Startup
```bash
# Terminal 1: Start Redis
redis-server

# Terminal 2: Start Celery Worker
cd fastapi
source ai_env/bin/activate
celery -A celery_app worker --loglevel=info

# Terminal 3: Start FastAPI
cd fastapi
source ai_env/bin/activate
python -m uvicorn fastapi_app:app --reload --host 0.0.0.0 --port 8000
```

### 4. Verify Installation

Open http://localhost:8000 in your browser to access the web interface.

## 📋 Usage Guide

### ESP32 Log Capture

#### One-Click Flash & Capture (Recommended)
```bash
# Basic usage
./flash_auto.sh /dev/ttyUSB0

# The script now automatically loads credentials from .env file
```

#### Manual Log Capture
```bash
# 1. Flash ESP32
idf.py flash -p /dev/ttyUSB0

# 2. Start log capture
cd esp32_catch
python3 catch_esp_log.py
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
LLM Analysis Engine (ZhiPu AI)
    │
    ▼
Web Interface + API
```

## 📁 Project Structure

```
AI_DEBUG_SYSTEM/
├── fastapi/                    # Backend services
│   ├── fastapi_app.py         # FastAPI main application
│   ├── celery_app.py          # Celery background tasks
│   ├── start_fastapi.sh       # Service startup script
│   └── requirements.txt       # Python dependencies
├── esp32_catch/               # ESP32 log capture
│   ├── catch_esp_log.py       # Serial log monitoring
│   └── logs/                  # Local log storage
├── config.yaml                # Central configuration file
├── .env.example               # Environment variables template
├── check_config.py            # Configuration validation tool
├── setup_docker.sh            # MinIO container setup
├── flash_auto.sh              # Flash + capture script
└── README.md                  # This file
```

## ⚙️ Configuration

### Central Configuration (`config.yaml`)
All system settings are managed through `config.yaml` with environment variable substitution:

```yaml
# Server settings
server:
  host: "0.0.0.0"
  port: 8000

# AI Service settings
ai:
  provider: "zhipu"
  model: "glm-4.5"
  api_key: "${ZHIPU_API_KEY}"

# MinIO settings
minio:
  endpoint: "localhost:9000"
  access_key: "${MINIO_ACCESS_KEY:minioadmin}"
  secret_key: "${MINIO_SECRET_KEY:minioadmin}"
```

### Environment Variables (`.env`)
Create `.env` file from `.env.example`:
```bash
# MinIO Configuration
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin

# AI Service Configuration (Required!)
ZHIPU_API_KEY=your-zhipu-api-key-here
```

## 🔧 Troubleshooting

### Common Issues

#### 1. Configuration Validation Failed
```bash
# Check configuration
python3 check_config.py

# Fix issues based on output
```

#### 2. MinIO Connection Issues
```bash
# Check MinIO container
sudo docker ps | grep minio

# Restart MinIO if needed
sudo docker restart minio

# Recreate MinIO with correct credentials
sudo docker stop minio && sudo docker rm minio
./setup_docker.sh
```

#### 3. Redis Connection Issues
```bash
# Check Redis status
redis-cli ping

# Start Redis if not running
sudo docker start redis  # if using Docker
# or
sudo systemctl start redis  # if using system package
```

#### 4. Missing Dependencies
```bash
# Install missing system dependencies
sudo apt install socat redis-server

# Install Python dependencies
source ai_env/bin/activate
pip install -r requirements.txt
```

#### 5. Virtual Serial Port Issues
```bash
# Check permissions
ls -la /tmp/ttyVLOG

# Create virtual serial port if needed
sudo socat -d -d /dev/ttyUSB0,raw,echo=0,b115200 PTY,link=/tmp/ttyVLOG,raw,echo=0,b115200 &
```

### Debug Mode

Enable debug logging:
```bash
# FastAPI debug mode
python -m uvicorn fastapi_app:app --reload --host 0.0.0.0 --port 8000 --log-level debug

# Celery debug mode
celery -A celery_app worker --loglevel=debug
```

### Health Checks

```bash
# Check FastAPI health
curl http://localhost:8000/health

# Check configuration
python3 check_config.py

# Check service status
docker ps | grep -E "(minio|redis)"
```

## 🔄 Development

### Configuration Changes
1. Edit `config.yaml` for system settings
2. Edit `.env` for sensitive credentials
3. Run `python3 check_config.py` to validate

### Adding New Features
1. Update `config.yaml` for new configuration options
2. Use `ConfigManager` in Python code:
   ```python
   from config_manager import get_config
   config = get_config()
   setting = config.get('section.key', 'default_value')
   ```

### Testing
```bash
# Run configuration validation
python3 check_config.py

# Test individual components
python3 -c "from config_manager import get_config; print(get_config().get_all_config())"
```

## 📊 Features

- **AI-Powered Analysis**: Intelligent log analysis using ZhiPu AI
- **Real-time Processing**: Live log capture and analysis
- **Interactive Q&A**: Ask questions about your logs
- **Web Interface**: User-friendly web dashboard
- **Parallel Processing**: Optimized for large log files
- **Caching System**: Intelligent result caching
- **Configuration Management**: Centralized YAML-based configuration

## 🔒 Security Notes

- Never commit `.env` files with real credentials
- Use different API keys for development and production
- Regularly rotate your API keys
- Monitor system logs for unusual activity

## 📝 License

This project is licensed under the LICENSE file in the repository.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Update documentation
5. Submit a pull request

## 📞 Support

For issues and questions:
- Check the troubleshooting section above
- Run `python3 check_config.py` for configuration validation
- Create an issue on GitHub
- Review the system architecture documentation

---

**Note**: This system is designed for ESP32 BLE debugging but can be adapted for other embedded systems with minimal configuration changes.