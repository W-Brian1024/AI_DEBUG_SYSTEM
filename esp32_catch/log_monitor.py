import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import requests
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI URL, assuming FastAPI service runs on localhost:8000
FASTAPI_URL = "http://localhost:8000/upload/"

# Local log folder path
LOCAL_LOG_FOLDER = "./logs"  # Relative path to logs directory

class LogFileHandler(FileSystemEventHandler):
    def __init__(self):
        # Used to record uploaded files and their last modification time, avoid duplicate uploads
        self.uploaded_files = {}

    def on_created(self, event):
        """
        Trigger upload when new file is created
        """
        if event.is_directory:
            return
        if event.src_path.endswith(".txt"):  # Only monitor .txt format log files
            logger.info(f"New log file detected: {event.src_path}")
            self.upload_file(event.src_path)

    def on_modified(self, event):
        """
        Trigger upload when existing file is modified
        """
        if event.is_directory:
            return
        if event.src_path.endswith(".txt"):  # Only monitor .txt format log files
            logger.info(f"Log file modified: {event.src_path}")
            self.upload_file(event.src_path)

    def upload_file(self, file_path):
        """
        Upload latest content of file, preserve file content without loss
        """
        try:
            # Get file's last modification timestamp
            last_modified_time = os.path.getmtime(file_path)
            
            # Check if file has already been uploaded, avoid duplicate uploads
            if file_path in self.uploaded_files and self.uploaded_files[file_path] == last_modified_time:
                logger.info(f"File {file_path} has not been modified. Skipping upload.")
                return

            # Upload entire file content
            with open(file_path, "rb") as log_file:
                files = {"file": log_file}
                metadata = {"device": "ESP32", "firmware": "v1.0", "timestamp": time.time()}
                response = requests.post(FASTAPI_URL, files=files, data={"metadata": metadata})

                if response.status_code == 200:
                    logger.info(f"Successfully uploaded: {file_path}")
                    self.uploaded_files[file_path] = last_modified_time  # Update file's last modification time
                else:
                    logger.error(f"Failed to upload {file_path}. Response: {response.text}")
        except Exception as e:
            logger.error(f"Error uploading {file_path}: {e}")

def start_monitoring():
    """
    Start watchdog to monitor folder
    """
    event_handler = LogFileHandler()
    observer = Observer()
    observer.schedule(event_handler, LOCAL_LOG_FOLDER, recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        logger.info("Stopped monitoring.")

    observer.join()

if __name__ == "__main__":
    # Start folder monitoring
    start_monitoring()
