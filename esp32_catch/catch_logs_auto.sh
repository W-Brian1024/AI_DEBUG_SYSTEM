#!/bin/bash
# One-click ESP32 log capture (virtual serial port + Python)

# === Dependency Check ===
check_dependencies() {
    local missing_deps=()

    # Check for socat
    if ! command -v socat &> /dev/null; then
        missing_deps+=("socat")
    fi

    # Check for python3
    if ! command -v python3 &> /dev/null; then
        missing_deps+=("python3")
    fi

    # Check for serial module in python3
    if ! python3 -c "import serial" &> /dev/null 2>&1; then
        missing_deps+=("pyserial")
    fi

    if [ ${#missing_deps[@]} -gt 0 ]; then
        echo "❌ Missing dependencies: ${missing_deps[*]}"
        echo ""
        echo "📦 Install commands:"
        for dep in "${missing_deps[@]}"; do
            case $dep in
                "socat")
                    echo "  sudo apt install socat"
                    ;;
                "python3")
                    echo "  sudo apt install python3"
                    ;;
                "pyserial")
                    echo "  pip3 install pyserial"
                    echo "  or: sudo apt install python3-serial"
                    ;;
            esac
        done
        echo ""
        echo "After installing, please run this script again."
        exit 1
    fi
}

# === Parameter Check ===
if [ -z "$1" ]; then
    echo "Usage: $0 <serial_port> [baud_rate]"
    echo "Example: $0 /dev/ttyUSB0 115200"
    exit 1
fi

# Check dependencies before proceeding
check_dependencies

PHYSICAL_SERIAL="$1"                  # ESP32 serial port passed from parameter
BAUD_RATE="${2:-115200}"              # Optional parameter, default 115200

# === Flash ESP32 ===
echo "🔥 Flashing ESP32 on $PHYSICAL_SERIAL..."
idf.py flash -p $PHYSICAL_SERIAL
if [ $? -eq 0 ]; then
    echo "✅ Flash completed successfully!"
else
    echo "❌ Flash failed! Exiting."
    exit 1
fi
echo ""

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

VIRTUAL_DIR="$HOME/vserial"           # Virtual serial port directory
VIRTUAL_SERIAL="$VIRTUAL_DIR/ttyVLOG"
PYTHON_SCRIPT="$SCRIPT_DIR/catch_esp_log.py"

# Create virtual serial port directory
mkdir -p "$VIRTUAL_DIR"

# Delete old virtual serial port files
[ -e "$VIRTUAL_SERIAL" ] && rm -f "$VIRTUAL_SERIAL"

# Start socat to create virtual serial port and set baud rate
echo "Starting socat on $PHYSICAL_SERIAL (baud=$BAUD_RATE)..."
socat -d -d "$PHYSICAL_SERIAL",raw,echo=0,b$BAUD_RATE \
          PTY,link="$VIRTUAL_SERIAL",raw,echo=0,b$BAUD_RATE &
SOCAT_PID=$!

# Wait for virtual serial port to be created (max 5 seconds)
timeout=5
elapsed=0
while [ ! -e "$VIRTUAL_SERIAL" ] && [ $elapsed -lt $timeout ]; do
    sleep 0.5
    elapsed=$((elapsed+1))
done

if [ ! -e "$VIRTUAL_SERIAL" ]; then
    echo "Error: Virtual serial port not created. Exiting."
    kill $SOCAT_PID 2>/dev/null
    exit 1
fi

echo "✅ Virtual serial port created at $VIRTUAL_SERIAL"

# Run Python script to capture logs
echo "📜 Running Python script to grab logs..."
VIRTUAL_SERIAL="$VIRTUAL_SERIAL" python3 "$PYTHON_SCRIPT"

# Safely close socat after Python script completes
if ps -p $SOCAT_PID > /dev/null; then
    echo "Stopping socat..."
    kill $SOCAT_PID
fi

echo "Done."
