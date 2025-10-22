#!/bin/bash
#
# Test script for data acquisition program
# This script tests the acq program without requiring hardware
# 

echo "=========================================="
echo "Testing Data Acquisition Program"
echo "=========================================="
echo ""

# Check if running with sudo
if [ "$EUID" -ne 0 ]; then 
    echo "WARNING: This program typically requires sudo for GPIO access"
    echo "If you get GPIO initialization errors, run with: sudo $0"
    echo ""
fi

# Check if output directory exists
OUTPUT_DIR="/home/peterson/Continuous_Sweep"
if [ ! -d "$OUTPUT_DIR" ]; then
    echo "Creating output directory: $OUTPUT_DIR"
    mkdir -p "$OUTPUT_DIR"
fi

# Display program configuration
echo "Program configuration:"
echo "  Binary: ./bin/acq"
echo "  Output directory: $OUTPUT_DIR"
echo "  Frequency range: 650-850 MHz"
echo "  Frequency step: 2.0 MHz"
echo "  Rows per sweep: 101"
echo "  State 2 max sweeps: 3"
echo ""
echo "The program will:"
echo "  1. Initialize AD HATs and GPIO"
echo "  2. Power on LO board"
echo "  3. Collect data sweeps continuously"
echo "  4. Exit after collecting 3 complete sweeps on state 2"
echo "  5. Perform clean shutdown"
echo ""
echo "To stop manually: Press Ctrl+C (will trigger clean shutdown)"
echo ""
read -p "Press Enter to start the test (or Ctrl+C to cancel)..."
echo ""

# Run the program
echo "Starting data acquisition..."
echo "=========================================="
./bin/acq

# Check exit status
EXIT_CODE=$?
echo ""
echo "=========================================="
if [ $EXIT_CODE -eq 0 ]; then
    echo "✓ Program exited successfully (exit code: $EXIT_CODE)"
else
    echo "✗ Program exited with error (exit code: $EXIT_CODE)"
fi
echo "=========================================="

# Show any created files
echo ""
echo "Checking for created FITS files..."
if [ -d "$OUTPUT_DIR" ]; then
    FILE_COUNT=$(ls -1 "$OUTPUT_DIR"/*.fits 2>/dev/null | wc -l)
    if [ $FILE_COUNT -gt 0 ]; then
        echo "Found $FILE_COUNT FITS file(s) in $OUTPUT_DIR:"
        ls -lth "$OUTPUT_DIR"/*.fits | head -5
    else
        echo "No FITS files found in $OUTPUT_DIR"
    fi
else
    echo "Output directory does not exist: $OUTPUT_DIR"
fi
