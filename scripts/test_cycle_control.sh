#!/bin/bash
#
# Test script for automated cycle controller
# Runs a short test cycle with minimal spectra counts
#

echo "=========================================="
echo "Testing Automated Cycle Controller"
echo "=========================================="
echo ""

# Check if running with sudo
if [ "$EUID" -ne 0 ]; then 
    echo "ERROR: This program requires sudo for GPIO access"
    echo "Please run with: sudo $0"
    exit 1
fi

# Configuration
TIMEZONE="-07:00"  # PST timezone (adjust as needed)
SPECTRA_CALIB=3    # Minimal count for calibration states (1-7)
SPECTRA_ANTENNA=10 # Minimal count for antenna state (0)

# Display test configuration
echo "Test Configuration:"
echo "  Binary: ./bin/cycle_control"
echo "  Timezone: $TIMEZONE"
echo "  Spectra (calibration states 1-7): $SPECTRA_CALIB"
echo "  Spectra (antenna state 0): $SPECTRA_ANTENNA"
echo ""
echo "This test will run ONE complete cycle (states 1→2→3→4→5→6→7→0)"
echo "with minimal spectra counts for quick validation."
echo ""
echo "Data will be saved to: /media/peterson/INDURANCE/Data/"
echo "Logs will be saved to: /media/peterson/INDURANCE/Logs/"
echo ""
echo "The cycle controller will:"
echo "  1. Initialize hardware (AD HATs, GPIO)"
echo "  2. Execute all 8 states in sequence"
echo "  3. Run filtercal sweeps in state 2"
echo "  4. Collect minimal spectra in each state"
echo "  5. Generate cycle metadata"
echo ""
echo "Expected duration: ~2-3 minutes for one complete cycle"
echo ""
echo "To stop: Press Ctrl+C (will trigger clean shutdown after current state)"
echo ""
read -p "Press Enter to start the test cycle (or Ctrl+C to cancel)..."
echo ""

# Run the cycle controller
echo "Starting cycle controller..."
echo "=========================================="
./bin/cycle_control --timezone "$TIMEZONE" --spectra-calib "$SPECTRA_CALIB" --spectra-antenna "$SPECTRA_ANTENNA"

# Check exit status
EXIT_CODE=$?
echo ""
echo "=========================================="
if [ $EXIT_CODE -eq 0 ]; then
    echo "✓ Cycle controller test completed successfully"
else
    echo "✗ Cycle controller exited with error code: $EXIT_CODE"
fi
echo ""
echo "Check the latest logs in /media/peterson/INDURANCE/Logs/ for details"
echo "=========================================="

exit $EXIT_CODE
