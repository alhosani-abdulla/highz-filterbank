#!/bin/bash
#
# Synchronized Spectrometer Control Script
#
# This script coordinates two measurement programs:
# 1. Continuous data acquisition (ADHAT_c_subroutine_NO_SOCKET)
# 2. Filter sweep calibration (filterSweep)
#
# The cycle runs continuously until manually stopped (Ctrl+C)
#

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Paths to executables
CONTINUOUS_ACQ="/home/peterson/highz/highz-filterbank/bin/acq"
FILTER_SWEEP="/home/peterson/highz/highz-filterbank/bin/calib"

# Parameters for continuous acquisition
NROWS=101  # Number of rows per buffer
START_FREQ=648
END_FREQ=850

# Cycle counter
CYCLE=0

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Synchronized Spectrometer Control${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Continuous acquisition: $CONTINUOUS_ACQ"
echo "Filter sweep: $FILTER_SWEEP"
echo "Parameters: nrows=$NROWS, freq range=$START_FREQ-$END_FREQ MHz"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
echo ""

# Trap Ctrl+C to exit cleanly
trap 'echo -e "\n${RED}Stopping synchronized sweep...${NC}"; exit 0' INT

while true; do
    CYCLE=$((CYCLE + 1))
    
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}Starting Cycle $CYCLE${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    
    # Phase 1: Run continuous acquisition until state 2 is detected
    echo -e "${BLUE}Phase 1: Continuous Data Acquisition${NC}"
    echo "Running: $CONTINUOUS_ACQ $NROWS $START_FREQ $END_FREQ"
    echo ""
    
    $CONTINUOUS_ACQ $NROWS $START_FREQ $END_FREQ
    ACQ_EXIT_CODE=$?
    
    echo ""
    echo -e "${YELLOW}Continuous acquisition ended (exit code: $ACQ_EXIT_CODE)${NC}"
    echo ""
    
    # Small delay for system to stabilize
    sleep 2
    
    # Phase 2: Run filter sweep calibration
    echo -e "${BLUE}Phase 2: Filter Sweep Calibration${NC}"
    echo "Running: $FILTER_SWEEP"
    echo ""
    
    sudo $FILTER_SWEEP
    CALIB_EXIT_CODE=$?
    
    echo ""
    echo -e "${YELLOW}Filter sweep calibration ended (exit code: $CALIB_EXIT_CODE)${NC}"
    echo ""
    
    # Small delay before next cycle
    echo -e "${YELLOW}Waiting 5 seconds before next cycle...${NC}"
    sleep 5
    echo ""
    
done
