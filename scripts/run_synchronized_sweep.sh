#!/bin/bash
#
# Synchronized Spectrometer Control Script
#
# This script coordinates two measurement programs that cannot run simultaneously
# (they share ADC hardware):
#
# State Sequence: 2→3→4→5→6→7→1(open)→0 → 1(antenna, long) → repeat
#
# Operation on State 2:
# 1. ACQ runs first, collecting STATE2_MAX_SWEEPS frequency sweeps (~10 seconds)
# 2. ACQ detects it has collected enough data and exits gracefully
# 3. CALIB starts and runs filter calibration (~20-30 seconds)
# 4. State transitions to next state (3)
# 5. ACQ resumes on state 3
#
# State 2 should be extended to ~40-50 seconds total to accommodate both programs.
#
# The cycle runs continuously until manually stopped (Ctrl+C)
#
# NOTE: Both programs now use hardcoded parameters defined in their source files:
#   - acq: 650-850 MHz, 2 MHz steps (101 measurements/sweep)
#   - calib: 900-960 MHz, 0.2 MHz steps (301 measurements/sweep)
#
# LOGGING:
#   All output is logged to: /media/peterson/INDURANCE/Logs/synchronized_sweep.log
#   Use 'tail -f /media/peterson/INDURANCE/Logs/synchronized_sweep.log' to monitor
#

# Setup logging
LOG_DIR="/media/peterson/INDURANCE/Logs"
LOG_FILE="$LOG_DIR/synchronized_sweep.log"

# Create log directory if it doesn't exist
if [ ! -d "$LOG_DIR" ]; then
    mkdir -p "$LOG_DIR"
    chmod 755 "$LOG_DIR"
fi

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# Color codes for output (only use when outputting to terminal)
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m' # No Color
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    NC=''
fi

# Paths to executables
CONTINUOUS_ACQ="/home/peterson/highz/highz-filterbank/bin/acq"
FILTER_SWEEP="/home/peterson/highz/highz-filterbank/bin/calib"

# Cycle counter
CYCLE=0

# Log startup
log "========================================="
log "Synchronized Spectrometer Control Starting"
log "========================================="
log "PID: $$"
log "User: $(whoami)"
log "Log file: $LOG_FILE"

log ""
log "Continuous acquisition: $CONTINUOUS_ACQ"
log "  • Data: 650-850 MHz, 2 MHz steps (101 measurements/sweep)"
log "  • Exits after STATE2_MAX_SWEEPS sweeps on state 2"
log ""
log "Filter sweep calibration: $FILTER_SWEEP"
log "  • Calibration: 900-960 MHz, 0.2 MHz steps (301 measurements/sweep)"
log "  • Dual power sweep: +5 dBm → -4 dBm"
log ""
log "Press Ctrl+C to stop"
log ""

# Trap Ctrl+C to exit cleanly
trap 'log ""; log "Stopping synchronized sweep..."; log "Shutdown at $(date)"; exit 0' INT TERM

while true; do
    CYCLE=$((CYCLE + 1))
    
    log "========================================"
    log "Starting Cycle $CYCLE"
    log "========================================"
    log ""
    
    # Phase 1: Run continuous acquisition until state 2 is detected
    log "Phase 1: Continuous Data Acquisition"
    log "Running: sudo $CONTINUOUS_ACQ"
    log ""
    
    # Run acq and capture all output to log
    sudo $CONTINUOUS_ACQ 2>&1 | tee -a "$LOG_FILE"
    ACQ_EXIT_CODE=${PIPESTATUS[0]}
    
    log ""
    log "Continuous acquisition ended (exit code: $ACQ_EXIT_CODE)"
    log ""
    
    # Small delay for system to stabilize
    sleep 2
    
    # Phase 2: Run filter sweep calibration
    log "Phase 2: Filter Sweep Calibration"
    log "Running: sudo $FILTER_SWEEP"
    log ""
    
    # Run calib and capture all output to log
    sudo $FILTER_SWEEP 2>&1 | tee -a "$LOG_FILE"
    CALIB_EXIT_CODE=${PIPESTATUS[0]}
    
    log ""
    log "Filter sweep calibration ended (exit code: $CALIB_EXIT_CODE)"
    log ""
    
    log "Cycle $CYCLE complete."
    
done
