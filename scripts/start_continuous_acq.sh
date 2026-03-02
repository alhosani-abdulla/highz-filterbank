#!/bin/bash
###############################################################################
# Start Continuous Data Acquisition (Persistent Background Mode)
###############################################################################
#
# This script starts the cycle controller in the background with proper
# process isolation so it survives terminal disconnects and can run
# unattended for extended periods.
#
# Features:
#   - Detached from terminal session (survives SSH disconnect)
#   - Logs to persistent file
#   - Saves PID for easy process management
#   - Validates binary exists before starting
#
# Usage:
#   ./scripts/start_continuous_acq.sh [OPTIONS]
#
# Options:
#   --tz OFFSET           Timezone offset (default: -07:00)
#   --spectra-calib N     Spectra per calibration state (default: 3)
#   --spectra-antenna N   Spectra for antenna state (default: 10)
#
# Management commands:
#   Check status:  sudo ps -p $(cat /tmp/cycle_control.pid)
#   View log:      tail -f /media/peterson/INDURANCE/Logs/cycle_persistent.log
#   Stop:          sudo kill $(cat /tmp/cycle_control.pid)
#                  OR use: ./scripts/stop_continuous_acq.sh
#
# Example:
#   ./scripts/start_continuous_acq.sh --tz -05:00 --spectra-calib 5 --spectra-antenna 15
#
###############################################################################

set -e  # Exit on error

# Default parameters
TZ_OFFSET="-07:00"
SPECTRA_CAL=3
SPECTRA_ANT=10

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --tz)
            TZ_OFFSET="$2"
            shift 2
            ;;
        --spectra-calib)
            SPECTRA_CAL="$2"
            shift 2
            ;;
        --spectra-antenna)
            SPECTRA_ANT="$2"
            shift 2
            ;;
        -h|--help)
            grep "^#" "$0" | grep -v "^#!/" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
BINARY="$REPO_DIR/bin/cycle_control"
PID_FILE="/tmp/cycle_control.pid"
LOG_FILE="/media/peterson/INDURANCE/Logs/cycle_persistent.log"

# Validate binary exists and is executable
if [[ ! -x "$BINARY" ]]; then
    echo "Error: Binary not found or not executable: $BINARY"
    echo "Run 'make' to build the software first."
    exit 1
fi

# Check if already running
if [[ -f "$PID_FILE" ]]; then
    EXISTING_PID=$(cat "$PID_FILE")
    if sudo ps -p "$EXISTING_PID" > /dev/null 2>&1; then
        echo "Error: Cycle controller is already running (PID: $EXISTING_PID)"
        echo "Stop it first with: sudo kill $EXISTING_PID"
        echo "Or use: ./scripts/stop_continuous_acq.sh"
        exit 1
    else
        echo "Stale PID file found, removing..."
        rm -f "$PID_FILE"
    fi
fi

echo "=========================================="
echo "Starting Continuous Data Acquisition"
echo "=========================================="
echo ""
echo "Configuration:"
echo "  Binary:        $BINARY"
echo "  Timezone:      $TZ_OFFSET"
echo "  Spectra (cal): $SPECTRA_CAL"
echo "  Spectra (ant): $SPECTRA_ANT"
echo "  Log file:      $LOG_FILE"
echo "  PID file:      $PID_FILE"
echo ""

# Start the cycle controller in background with proper detachment
# - setsid: Creates new session, detaches from terminal
# - nohup: Ignores SIGHUP signal
# - </dev/null: Redirects stdin from /dev/null (no input)
# - >/log 2>&1: Redirects both stdout and stderr to log file
cd "$REPO_DIR"

# Create temporary PID holder (cleanup with sudo if needed)
TEMP_PID="/tmp/cycle_control_temp.pid"
sudo rm -f "$TEMP_PID"

# Start the process in background with proper isolation
sudo bash -c "
    setsid nohup '$BINARY' \
        --timezone '$TZ_OFFSET' \
        --spectra-calib $SPECTRA_CAL \
        --spectra-antenna $SPECTRA_ANT \
        > '$LOG_FILE' 2>&1 < /dev/null &
    echo \$! > '$TEMP_PID'
    chmod 644 '$TEMP_PID'
"

# Read the PID and create the official PID file
if [[ -f "$TEMP_PID" ]]; then
    PID=$(cat "$TEMP_PID")
    echo "$PID" > "$PID_FILE"
    sudo rm -f "$TEMP_PID"
fi

# Wait a moment for process to start
sleep 1

# Verify it started successfully
if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE")
    if sudo ps -p "$PID" > /dev/null 2>&1; then
        echo "✓ Cycle controller started successfully"
        echo ""
        echo "Process ID: $PID"
        echo ""
        echo "Management commands:"
        echo "  Check status:  sudo ps -p $PID"
        echo "  View log:      tail -f $LOG_FILE"
        echo "  Stop:          ./scripts/stop_continuous_acq.sh"
        echo ""
        echo "You can now safely disconnect. Data acquisition will continue."
        echo "=========================================="
    else
        echo "✗ Failed to start cycle controller"
        echo "Check the log file: $LOG_FILE"
        exit 1
    fi
else
    echo "✗ Failed to create PID file"
    exit 1
fi
