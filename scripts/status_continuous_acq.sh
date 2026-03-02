#!/bin/bash
###############################################################################
# Check Continuous Data Acquisition Status
###############################################################################
#
# This script checks the status of the cycle controller and shows recent
# data acquisition activity.
#
# Usage:
#   ./scripts/status_continuous_acq.sh
#
###############################################################################

PID_FILE="/tmp/cycle_control.pid"
LOG_FILE="/media/peterson/INDURANCE/Logs/cycle_persistent.log"
DATA_DIR="/media/peterson/INDURANCE/Data"

echo "=========================================="
echo "Continuous Data Acquisition Status"
echo "=========================================="
echo ""

# Check if PID file exists
if [[ ! -f "$PID_FILE" ]]; then
    echo "Status: NOT RUNNING"
    echo "  (No PID file found)"
    echo ""
    echo "To start: ./scripts/start_continuous_acq.sh"
    exit 0
fi

PID=$(cat "$PID_FILE")

# Check if process is running
if ! sudo ps -p "$PID" > /dev/null 2>&1; then
    echo "Status: NOT RUNNING"
    echo "  (Stale PID file found: $PID)"
    echo ""
    echo "To clean up: rm $PID_FILE"
    echo "To start: ./scripts/start_continuous_acq.sh"
    exit 0
fi

# Process is running - show details
echo "Status: RUNNING ✓"
echo ""
echo "Process Information:"
sudo ps -p "$PID" -o pid,ppid,%cpu,%mem,etime,cmd --no-headers | \
    awk '{printf "  PID:        %s\n  Parent PID: %s\n  CPU:        %s%%\n  Memory:     %s%%\n  Uptime:     %s\n  Command:    %s\n", $1, $2, $3, $4, $5, substr($0, index($0,$6))}'
echo ""

# Show recent log activity
if [[ -f "$LOG_FILE" ]]; then
    echo "Recent Log Activity (last 15 lines):"
    echo "────────────────────────────────────────"
    tail -15 "$LOG_FILE" | sed 's/^/  /'
    echo "────────────────────────────────────────"
    echo ""
    echo "Full log: $LOG_FILE"
else
    echo "Log file not found: $LOG_FILE"
fi
echo ""

# Show latest data directory
LATEST_CYCLE=$(ls -td "$DATA_DIR"/*/Cycle_* 2>/dev/null | head -1)
if [[ -n "$LATEST_CYCLE" ]]; then
    echo "Latest Data:"
    echo "  Directory: $(basename "$LATEST_CYCLE")"
    echo "  Modified:  $(stat -c '%y' "$LATEST_CYCLE" | cut -d. -f1)"
    
    # Count files in latest cycle
    NUM_FILES=$(find "$LATEST_CYCLE" -type f -name "*.fits" 2>/dev/null | wc -l)
    echo "  Files:     $NUM_FILES FITS files"
fi

echo ""
echo "Management Commands:"
echo "  View log:  tail -f $LOG_FILE"
echo "  Stop:      ./scripts/stop_continuous_acq.sh"
echo "=========================================="
