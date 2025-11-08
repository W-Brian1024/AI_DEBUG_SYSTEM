import serial
import time
import os
import sys
from datetime import datetime
import requests

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import configuration management
from check_config.config_manager import get_config

# Initialize configuration
config_manager = get_config()
esp32_config = config_manager.get_esp32_config()
server_config = config_manager.get_server_config()

# Get script directory and log directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Use script-local logs directory, ignore config setting to avoid confusion
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Virtual serial port and baud rate from configuration
SERIAL_PORT = os.environ.get("VIRTUAL_SERIAL", esp32_config.get('virtual_serial_path', '/tmp/ttyVLOG'))
BAUD_RATE = esp32_config.get('default_baud_rate', 115200)
TIMEOUT_NO_LOG = esp32_config.get('timeout_no_log', 20)  # seconds
FASTAPI_URL = f"http://{server_config.get('host', 'localhost')}:{server_config.get('port', 8000)}/upload/"

# Used to save last read file pointer position, avoid duplicate uploads
last_pos = 0

def upload_file(file_path):
    """Upload file content to FastAPI and trigger Celery task"""
    try:
        # Read file and prepare for upload
        with open(file_path, "rb") as log_file:
            files = {"file": log_file}
            metadata = {"device": "ESP32", "firmware": "v1.0", "timestamp": time.time()}
            
            # Send POST request to FastAPI
            response = requests.post(FASTAPI_URL, files=files, data={"metadata": metadata})
            
            if response.status_code == 200:
                # Get event_id and task ID returned by FastAPI
                response_data = response.json()
                event_id = response_data.get("event_id")
                task_id = response_data.get("task_id")
                minio_path = response_data.get("minio_path")
                
                print(f"✅ Successfully uploaded {file_path} to FastAPI.")
                print(f"event_id: {event_id}, task_id: {task_id}, minio_path: {minio_path}")
            else:
                print(f"❌ Failed to upload {file_path}. Response: {response.text}")
    except Exception as e:
        print(f"❌ Error uploading {file_path}: {e}")


def open_new_log_file():
    """Create new log file"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(LOG_DIR, f"esp32_{timestamp}.txt")
    print(f"[INFO] New log file: {filename}")
    return open(filename, "w", encoding="utf-8"), filename

def delete_old_logs():
    """Delete all old log files"""
    for f in os.listdir(LOG_DIR):
        if f.startswith("esp32_"):
            os.remove(os.path.join(LOG_DIR, f))
            print(f"[INFO] Deleted old log file: {f}")

def main():
    global last_pos
    log_file = None
    current_file = None
    last_log_time = time.time()
    logs_exist = False

    while True:
        try:
            with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1) as ser:
                while True:
                    line = ser.readline().decode(errors="ignore").strip()
                    now = time.time()

                    if line:
                        # If file is empty or no file exists, create a new file
                        if log_file is None or log_file.closed:
                            # Delete all old files then create new file
                            delete_old_logs()
                            log_file, current_file = open_new_log_file()

                        # Write logs to file
                        log_file.write(line + "\n")
                        log_file.flush()
                        print(line)

                        # Record current timestamp
                        last_log_time = now

                    # No logs for TIMEOUT_NO_LOG seconds → close current log file, but don't generate new file
                    if log_file and now - last_log_time > TIMEOUT_NO_LOG:
                        if log_file and not log_file.closed:
                            log_file.close()  # Close file
                        print(f"[INFO] No log for {TIMEOUT_NO_LOG}s. File saved: {current_file}")
                        
                        # Ensure file is closed before uploading
                        if os.path.exists(current_file):  # Ensure file exists
                            print("[INFO] please enter http://localhost:8000/, and upload the file")
                            # upload_file(current_file)

                        log_file = None
                        current_file = None  # Reset, prepare for next log processing

        except serial.SerialException as e:
            print(f"[WARN] Serial exception: {e}. Retrying in 2s...")
            time.sleep(2)

        except KeyboardInterrupt:
            print("[INFO] Ctrl+C detected, exiting...")
            if log_file and not log_file.closed:
                log_file.close()
            break

if __name__ == "__main__":
    main()

