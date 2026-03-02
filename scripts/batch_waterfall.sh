#!/bin/bash

# Batch waterfall plotter for all filters and states
# Usage: ./batch_waterfall_plotter.sh [DATE] [filters_to_process]
# DATE format: YYYYMMDD (e.g., 20251102 for Nov 2, 2025)
# If no date provided, defaults to 20251102
# If no filters specified, processes all 21 filters

# Change to Highz-EXP directory
cd /Users/abdullaalhosani/Projects/highz/Highz-EXP

# Get date from first argument or use default
DATE="${1:-20251102}"
shift || true  # Remove first argument if it exists

DATA_PATH="/Users/abdullaalhosani/Projects/highz/Data/LunarDryLake/2025Nov/filterbank/Bandpass_consolidated/$DATE"
# Extract day from date (last 2 digits) and remove leading zero
DAY=$(echo $DATE | cut -c7-8 | sed 's/^0//')
OUTPUT_BASE="/Users/abdullaalhosani/Projects/highz/plots/Nov${DAY}"
REFERENCE_SPECTRUM="cycle_001:0"
POWER_RANGE="-70 -20"

# Check if data directory exists
if [ ! -d "$DATA_PATH" ]; then
    echo "Error: Data directory not found: $DATA_PATH"
    exit 1
fi

echo "Date: $DATE"
echo "Data path: $DATA_PATH"
echo "Output base: $OUTPUT_BASE"
echo ""

# States to process
STATES=(0 1 2 3 4 5 6 7 1_OC)

# Determine which filters to process
if [ $# -eq 0 ]; then
    # Process all 21 filters (0-20)
    FILTERS=$(seq 0 20)
    echo "Processing all 21 filters (0-20)..."
else
    # Process specified filters
    FILTERS="$@"
    echo "Processing filters: $FILTERS"
fi

# Track progress
TOTAL_JOBS=0
FAILED_JOBS=0

for FILTER in $FILTERS; do
    # Convert 0-based index to 1-based directory name
    FILTER_DIR=$((FILTER + 1))
    
    # Create filter-specific output directory
    FILTER_OUTPUT="$OUTPUT_BASE/filter${FILTER_DIR}"
    mkdir -p "$FILTER_OUTPUT"
    
    echo ""
    echo "=========================================="
    echo "Processing Filter $FILTER_DIR (index $FILTER)"
    echo "=========================================="
    
    for STATE in "${STATES[@]}"; do
        TOTAL_JOBS=$((TOTAL_JOBS + 1))
        
        CMD="pipenv run python tools/waterfall_plotter.py $DATA_PATH --state $STATE --filter $FILTER --reference-spectrum $REFERENCE_SPECTRUM --output $FILTER_OUTPUT --power-range $POWER_RANGE --no-interactive"
        
        echo "  [$(date +'%H:%M:%S')] Processing state $STATE..."
        
        if eval "$CMD" > /dev/null 2>&1; then
            echo "    ✓ State $STATE completed"
        else
            echo "    ✗ State $STATE FAILED (exit code: $?)"
            FAILED_JOBS=$((FAILED_JOBS + 1))
        fi
    done
done

echo ""
echo "=========================================="
echo "BATCH PROCESSING COMPLETE"
echo "=========================================="
echo "Total jobs: $TOTAL_JOBS"
echo "Failed jobs: $FAILED_JOBS"
echo "Successful jobs: $((TOTAL_JOBS - FAILED_JOBS))"
echo ""
echo "Output directory: $OUTPUT_BASE"
