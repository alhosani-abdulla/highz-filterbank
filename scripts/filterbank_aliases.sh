#!/bin/bash
###############################################################################
# High-Z Filterbank Shell Aliases
###############################################################################
#
# This file defines convenient shell aliases for common filterbank operations.
#
# Usage:
#   Source this file in your shell:
#     source ~/highz/highz-filterbank/scripts/filterbank_aliases.sh
#
#   Or add to your ~/.bashrc:
#     source ~/highz/highz-filterbank/scripts/filterbank_aliases.sh
#
# Available aliases:
#   fb-start     - Start continuous data acquisition
#   fb-stop      - Stop data acquisition
#   fb-status    - Check acquisition status
#   fb-viewer    - Launch live viewer
#   fb-log       - Tail the acquisition log
#   fb-data      - Go to data directory
#   fb-repo      - Go to repository directory
#
###############################################################################

# Detect repository location
if [[ -d "$HOME/highz/highz-filterbank" ]]; then
    FB_REPO="$HOME/highz/highz-filterbank"
elif [[ -d "$HOME/highz-filterbank" ]]; then
    FB_REPO="$HOME/highz-filterbank"
else
    echo "Warning: Could not find highz-filterbank repository"
    FB_REPO=""
fi

# Data and log locations
FB_DATA_DIR="/media/peterson/INDURANCE/Data"
FB_LOG_FILE="/media/peterson/INDURANCE/Logs/cycle_persistent.log"

# Aliases for data acquisition
if [[ -n "$FB_REPO" ]]; then
    alias fb-start="cd $FB_REPO && ./scripts/start_continuous_acq.sh"
    alias fb-stop="cd $FB_REPO && ./scripts/stop_continuous_acq.sh"
    alias fb-status="cd $FB_REPO && ./scripts/status_continuous_acq.sh"
    alias fb-viewer="cd $FB_REPO && ./run_live_viewer.sh"
    alias fb-repo="cd $FB_REPO"
fi

# Aliases for logs and data
alias fb-log="tail -f $FB_LOG_FILE"
alias fb-log-all="less $FB_LOG_FILE"
alias fb-data="cd $FB_DATA_DIR && ls -lhtr | tail -20"
alias fb-data-today="cd $FB_DATA_DIR/\$(date +%m%d%Y) && ls -lhtr | tail -20"

# Function: Quick start with custom parameters
fb-start-custom() {
    if [[ -z "$FB_REPO" ]]; then
        echo "Error: Repository not found"
        return 1
    fi
    
    local tz="${1:--07:00}"
    local cal="${2:-3}"
    local ant="${3:-10}"
    
    echo "Starting with:"
    echo "  Timezone: $tz"
    echo "  Calib spectra: $cal"
    echo "  Antenna spectra: $ant"
    
    cd "$FB_REPO" && ./scripts/start_continuous_acq.sh --tz "$tz" --spectra-calib "$cal" --spectra-antenna "$ant"
}

# Function: Monitor latest cycle
fb-watch() {
    if [[ ! -d "$FB_DATA_DIR" ]]; then
        echo "Error: Data directory not found: $FB_DATA_DIR"
        return 1
    fi
    
    echo "Monitoring latest cycle directory..."
    while true; do
        clear
        LATEST=$(find "$FB_DATA_DIR" -type d -name "Cycle_*" 2>/dev/null | sort | tail -1)
        if [[ -n "$LATEST" ]]; then
            echo "Latest cycle: $(basename "$LATEST")"
            echo "Modified: $(stat -c '%y' "$LATEST" | cut -d. -f1)"
            echo ""
            echo "Contents:"
            ls -lhtr "$LATEST" | tail -10
        else
            echo "No cycles found"
        fi
        sleep 5
    done
}

# Function: Show status with recent cycles
fb-info() {
    echo "=========================================="
    echo "High-Z Filterbank Quick Info"
    echo "=========================================="
    echo ""
    
    # Acquisition status
    if [[ -f /tmp/cycle_control.pid ]]; then
        PID=$(cat /tmp/cycle_control.pid)
        if sudo ps -p "$PID" > /dev/null 2>&1; then
            echo "Status: RUNNING ✓ (PID: $PID)"
            UPTIME=$(ps -p "$PID" -o etime= | tr -d ' ')
            echo "Uptime: $UPTIME"
        else
            echo "Status: NOT RUNNING (stale PID)"
        fi
    else
        echo "Status: NOT RUNNING"
    fi
    echo ""
    
    # Recent cycles
    echo "Recent cycles:"
    find "$FB_DATA_DIR" -maxdepth 2 -type d -name "Cycle_*" 2>/dev/null | sort | tail -5 | while read cycle; do
        echo "  $(basename "$cycle") - $(stat -c '%y' "$cycle" | cut -d. -f1)"
    done
    echo ""
    
    # Log tail
    if [[ -f "$FB_LOG_FILE" ]]; then
        echo "Recent log (last 5 lines):"
        tail -5 "$FB_LOG_FILE" | sed 's/^/  /'
    fi
    echo "=========================================="
}

# Print help
fb-help() {
    cat << 'EOF'
High-Z Filterbank Aliases
=========================

Data Acquisition:
  fb-start          - Start continuous data acquisition (default settings)
  fb-stop           - Stop data acquisition
  fb-status         - Check acquisition status and recent activity
  fb-start-custom   - Start with custom parameters
                      Usage: fb-start-custom [tz] [calib_n] [antenna_n]
                      Example: fb-start-custom -05:00 5 15

Monitoring:
  fb-viewer         - Launch live web viewer
  fb-log            - Follow acquisition log (Ctrl+C to exit)
  fb-log-all        - View full log file
  fb-watch          - Monitor latest cycle directory (refreshes every 5s)
  fb-info           - Quick status overview

Navigation:
  fb-repo           - Go to filterbank repository
  fb-data           - Go to data directory and show recent cycles
  fb-data-today     - Go to today's data directory

For detailed help:
  fb-start --help
  fb-status

EOF
}

# Print welcome message
echo "High-Z Filterbank aliases loaded. Type 'fb-help' for usage."
