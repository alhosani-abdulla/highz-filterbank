#!/bin/bash
# Consolidate all 6 November days with filter calibrations

cd /Users/abdullaalhosani/Projects/highz/Highz-EXP

FILTERCAL_DIR="/Users/abdullaalhosani/Projects/highz/Data/LunarDryLake/2025Nov/filterbank/filtercalibrations"
OUTPUT_DIR="/Users/abdullaalhosani/Projects/highz/Data/LunarDryLake/2025Nov/filterbank/Bandpass_consolidated"
BANDPASS_DIR="/Users/abdullaalhosani/Projects/highz/Data/LunarDryLake/2025Nov/filterbank/Bandpass"

DAYS=(
  "11012025"
  "11022025"
  "11032025"
  "11042025"
  "11052025"
  "11062025"
)

echo "Starting consolidation of all 6 days with filter calibrations..."
echo "================================================================"
echo ""

for day in "${DAYS[@]}"; do
  echo "Processing $day..."
  pipenv run python scripts/consolidate_filterbank_data.py \
    --filtercal-dir "$FILTERCAL_DIR" \
    --output "$OUTPUT_DIR" \
    "$BANDPASS_DIR/$day"
  
  if [ $? -eq 0 ]; then
    echo "✓ $day completed successfully"
  else
    echo "✗ $day failed with error code $?"
  fi
  echo ""
done

echo "================================================================"
echo "All days processed!"
