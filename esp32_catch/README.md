# ESP32 Log Capture

自动捕获 ESP32 串口日志并保存到本地。

## 快速使用

**方式1：一键启动（推荐）**
```bash
./catch_logs_auto.sh /dev/ttyUSB0
```

**方式2：手动启动**
```bash
# 1. 创建虚拟串口
socat /dev/ttyUSB0,raw,echo=0,b115200 PTY,link=/tmp/ttyVLOG,raw,echo=0,b115200 &

# 2. 启动捕获
python3 catch_esp_log.py
```

## 文件说明

- `catch_esp_log.py` - 主程序：读取串口日志并保存
- `log_monitor.py` - 可选：监控日志文件自动上传
- `catch_logs_auto.sh` - 一键启动脚本
- `logs/` - 日志保存目录

## 配置

所有配置在项目根目录的 `config.yaml` 中（波特率、超时时间等）。

日志文件会在 `logs/` 目录自动生成，命名格式：`esp32_20250105_143022.txt`
