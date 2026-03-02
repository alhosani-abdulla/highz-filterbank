#!/bin/bash
###############################################################################
# Stop Continuous Data Acquisition
###############################################################################
#
# This script cleanly stops the cycle controller that was started with
# start_continuous_acq.sh
#
# Usage:
#   ./scripts/stop_continuous_acq.sh
#
###############################################################################

set -e

PID_FILE="/tmp/cycle_control.pid"

echo "=========================================="
echo "Stopping Continuous Data Acquisition"
echo "=========================================="
echo ""

# Check if PID file exists
if [[ ! -f "$PID_FILE" ]]; then
    echo "No PID file found at: $PID_FILE"
    echo "The cycle controller may not be running, or was started manually."
    echo ""
    echo "To check manually: ps aux | grep cycle_control"
    exit 1
fi

PID=$(cat "$PID_FILE")

# Check if process is actually running
if ! sudo ps -p "$PID" > /dev/null 2>&1; then
    echo "Process $PID is not running (stale PID file)"
    rm -f "$PID_FILE"
    echo "Cleaned up stale PID file."
    exit 0
fi

# Get process info before stopping
PROCESS_INFO=$(sudo ps -p "$PID" -o pid,etime,cmd --no-headers)
echo "Found running process:"
echo "  $PROCESS_INFO"
echo ""

# Send SIGTERM for clean shutdown
echo "Sending SIGTERM (clean shutdown signal)..."
sudo kill "$PID"

# Wait for process to terminate (up to 30 seconds)
echo "Waiting for process to terminate..."
for i in {1..30}; do
    if ! sudo ps -p "$PID" > /dev/null 2>&1; then
        echo "✓ Process terminated cleanly"
        rm -f "$PID_FILE"
        echo "✓ Removed PID file"
        echo ""
        echo "Cycle controller stopped successfully."
        echo "=========================================="
        exit 0
    fi
    sleep 1
    echo -n "."
done
echo ""

# If still running after 30 seconds, force kill
echo "Process did not terminate cleanly, forcing shutdown..."
sudo kill -9 "$PID" 2>/dev/null || true
sleep 1

if sudo ps -p "$PID" > /dev/null 2>&1; then
    echo "✗ Failed to stop process"
    exit 1
else
    echo "✓ Process forcefully terminated"
    rm -f "$PID_FILE"
    echo "✓ Removed PID file"
    echo ""
    echo "Cycle controller stopped (forced)."
    echo "=========================================="
fi
