# ESP32 Log Capture

Automatically capture ESP32 serial port logs and save to local files.

## Quick Start

**Method 1: One-Click Launch (Recommended)**
```bash
./catch_logs_auto.sh /dev/ttyUSB0
```

**Method 2: Manual Launch**
```bash
# 1. Create virtual serial port
socat /dev/ttyUSB0,raw,echo=0,b115200 PTY,link=/tmp/ttyVLOG,raw,echo=0,b115200 &

# 2. Start capture
python3 catch_esp_log.py
```

## Files

- `catch_esp_log.py` - Main script: reads serial logs and saves to files
- `log_monitor.py` - Optional: monitors and auto-uploads log files
- `catch_logs_auto.sh` - One-click launch script
- `logs/` - Log storage directory

## Configuration

All settings are in `config.yaml` at project root (baud rate, timeout, etc.).

Logs are automatically saved in `logs/` directory with format: `esp32_20250105_143022.txt`
