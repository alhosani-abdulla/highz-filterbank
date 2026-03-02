# Filterbank Spectrometer Data Consolidation

**For High-Z Filterbank Spectrometer** (not the digital spectrometer)

## Overview

This document describes the consolidation strategy for the High-Z filterbank spectrometer data. The `consolidate.py` script converts individual spectrum FITS files into consolidated cycle-based directories with image cube format for efficient storage and analysis.

---

## Current FITS File Structure

Each individual spectrum FITS file contains:
- **Primary HDU:** Empty header with standard FITS metadata
- **Binary Table Extension (HDU 1):** "FILTER BANK DATA"
  - **ADHAT_1** (7K int64): ADC readings from detector 1 (7 cavity filters)
  - **ADHAT_2** (7K int64): ADC readings from detector 2 (7 cavity filters)
  - **ADHAT_3** (7K int64): ADC readings from detector 3 (7 cavity filters)
  - **TIME_RPI2** (25A string): Timestamp/filename identifier
  - **SWITCH STATE** (15A string): Observing state (0-7 or "1" for sky)
  - **FREQUENCY** (15A string): LO frequency in MHz
  - **FILENAME** (25A string): Original source filename

- **Header Keyword:** `SYSVOLT` - System voltage

**Current Data Structure:**
- **144 rows per FITS file** = 144 different LO frequency sweep points
- **3 detector columns × 7 filters each = 21 total cavity filters**
- **One complete measurement = one LO sweep across all 21 filters**
- **Data cube per measurement:** 21 (filters) × 144 (LO points) = 3,024 ADC values
- One FITS file per spectrum (~3-3.2 seconds per measurement)

---

## Consolidated Data Format

### Image Cube Format

The key insight: **Each measurement produces a 3D data cube:**
- **Axis 1 (Filters):** 21 cavity filters (center frequencies range 904-956 MHz)
- **Axis 2 (LO Frequency):** 144 LO sweep points 
- **Axis 3 (Time):** Multiple measurements over cycle duration

For any single measurement at time T:
- Extract a **21 × 144 data cube** containing all ADC values for all filters across all LO points
- Reshape the flat 3,024 values into this 2D array
- Each filter channel can then be converted back to original signal frequency using: `original_freq = LO_freq - (filter_center_freq - measured_offset)`

### Directory Organization

```
Data/LunarDryLake/2025Nov/filterbank/Bandpass_consolidated/
├── 20251104/                          # Date directory (YYYYMMDD)
│   ├── cycle_001_11042025_040632/     # Cycle directory
│   │   ├── cycle_metadata.json
│   │   ├── state_0.fits               # 6 measurements
│   │   ├── state_1_OC.fits            # 6 measurements (open circuit calibration)
│   │   ├── state_1.fits               # 280+ measurements (sky observing)
│   │   ├── state_2.fits               # 6 measurements (50Ω load)
│   │   ├── state_3.fits               # 6 measurements
│   │   ├── state_4.fits               # 6 measurements
│   │   ├── state_5.fits               # 6 measurements
│   │   ├── state_6.fits               # 6 measurements
│   │   ├── state_7.fits               # 6 measurements
│   │   ├── filtercal_+5dBm.fits       # Filter calibration (optional)
│   │   └── filtercal_-4dBm.fits       # Filter calibration (optional)
│   ├── cycle_002_11042025_054323/
│   └── ...
└── 20251105/                          # Next day
    └── ...
```

### Consolidated FITS File Format per State

**Primary HDU Header:**
- `CYCLE_ID`: Cycle identifier (e.g., "cycle_001")
- `STATE`: Observing state (0-7, "1_OC" for open circuit calibration, etc.)
- `N_FILTERS`: 21 (number of cavity filters)
- `N_LO_POINTS`: 144 (number of LO frequency sweep points)
- `ANTENNA`: Antenna identifier (1-4)
- `ANT_SIZE`: Antenna aperture diameter
- `ANT_NOTE`: Antenna configuration notes

**Binary Table Extension:**

One row per measurement/timestamp:

- **DATA_CUBE** (3024J): Flattened 21×144 int64 array (reshape to (21, 144) for use)
- **SPECTRUM_TIMESTAMP** (25A string): ISO 8601 timestamp for this measurement
- **SPECTRUM_INDEX** (1J int32): Sequential measurement index within state
- **SYSVOLT** (1E float32): System voltage for this measurement
- **LO_FREQUENCIES** (144E float32): LO frequency values for this measurement

**Example FITS structure:**
```
state_2.fits (6 total measurements for state 2):
├─ Row 1: 21×144 cube at T1 + metadata
├─ Row 2: 21×144 cube at T2 + metadata
├─ Row 3: 21×144 cube at T3 + metadata
├─ Row 4: 21×144 cube at T4 + metadata
├─ Row 5: 21×144 cube at T5 + metadata
└─ Row 6: 21×144 cube at T6 + metadata

state_1.fits (280+ measurements for sky observation):
├─ Row 1: 21×144 cube at T1 + metadata
├─ Row 2: 21×144 cube at T2 + metadata
├─ ...
└─ Row 281: 21×144 cube at T281 + metadata
```

### Metadata Structure (cycle_metadata.json)

```json
{
  "cycle_id": "cycle_001",
  "cycle_number": 1,
  "date": "2025-11-04",
  "start_time": "2025-11-04T04:06:32",
  "end_time": "2025-11-04T04:24:15",
  "timezone": "EDT (GMT-4)",
  "duration_minutes": 18.2,
  "antenna": {
    "antenna_id": "4",
    "antenna_size": "10m",
    "notes": "Largest antenna"
  },
  "state_sequence": ["2", "3", "4", "5", "6", "7", "1_OC", "0", "1"],
  "spectra_counts": {
    "state_0": 6,
    "state_1_OC": 6,
    "state_2": 6,
    "state_3": 6,
    "state_4": 6,
    "state_5": 6,
    "state_6": 6,
    "state_7": 6,
    "state_1": 281
  },
  "total_spectra": 335,
  "total_adc_values": 1010400,
  "lo_frequencies": [882.0, 883.0],
  "filter_centers_mhz": [904.0, 906.6, 909.2, 911.8, 914.4, 917.0, 919.6, 922.2, 924.8, 927.4, 930.0, 932.6, 935.2, 937.8, 940.4, 943.0, 945.6, 948.2, 950.8, 953.4, 956.0],
  "system_voltage_stats": {
    "mean": 11.167,
    "min": 11.155,
    "max": 11.182
  },
  "calibration_files": {
    "positive_5dbm": "filtercal_+5dBm.fits",
    "negative_4dbm": "filtercal_-4dBm.fits"
  },
  "data_format_version": "1.0",
  "notes": "Consolidated from individual spectrum FITS files into image cube format"
}
```

**Note on Antenna Configuration:**
The antenna field records which antenna was used during data collection. During the Nov 2025 Lunar Dry Lake campaign:
- **Antenna 4 (10m)**: Nov 1-3 - Largest aperture
- **Antenna 3 (7m)**: Nov 3 - Second largest
- **Antenna 2 (5m)**: Nov 4 - Medium
- **Antenna 1 (3m)**: Nov 5-6 - Smallest, with 34 MHz high-pass filter

---

## Key Features

### 1. **Cycle Detection**
- Automatically detects cycles based on state sequence progression: `2→3→4→5→6→7→1(cal)→0→1(sky)`
- Expected ~350 spectra per cycle (±5 tolerance)
- Handles day boundaries correctly

### 2. **Day Boundary Handling**
- **Cycles that span midnight are kept together**
- Directory is based on cycle **start time**
- Example: Cycle starting at 23:52 on Nov 4 and ending at 00:10 on Nov 5 will be stored in `20251104/cycle_074_11042025_235217/`
- All spectra from that cycle stay together, even if timestamps cross into the next day

### 3. **Cycle Categories**

| Category | Description | Include By Default |
|----------|-------------|-------------------|
| **Normal** | Correct sequence (2→3→4→5→6→7→1→0→1) + 345-355 spectra | ✓ Yes |
| **Partial** | Wrong sequence but 345-355 spectra (interrupted/day-boundary) | ✗ No (use `--include-partial`) |
| **Abnormal** | Wrong count AND/OR very abnormal sequence | ✗ No |

---

## Usage

### Using the Module Directly (Python)

```python
from filterbank.consolidation import consolidate

# Dry run to preview cycles
consolidate.consolidate_directory(
    input_dir='/path/to/Bandpass/11042025',
    output_base='/path/to/Bandpass_consolidated',
    dry_run=True
)

# Process only normal cycles
consolidate.consolidate_directory(
    input_dir='/path/to/Bandpass/11042025',
    output_base='/path/to/Bandpass_consolidated',
    skip_abnormal=True
)

# Include partial cycles (day boundaries)
consolidate.consolidate_directory(
    input_dir='/path/to/Bandpass/11042025',
    output_base='/path/to/Bandpass_consolidated',
    skip_abnormal=True,
    include_partial=True
)
```

### Command-Line Usage

```bash
# Dry run - preview cycles without writing
pipenv run python -m filterbank.consolidation.consolidate --dry-run \
  /path/to/Bandpass/11042025

# Process only normal cycles
pipenv run python -m filterbank.consolidation.consolidate --skip-abnormal \
  /path/to/Bandpass/11042025

# Include partial cycles (day boundaries)
pipenv run python -m filterbank.consolidation.consolidate --skip-abnormal --include-partial \
  /path/to/Bandpass/11042025

# Custom output directory
pipenv run python -m filterbank.consolidation.consolidate \
  --output /custom/path/Consolidated \
  /path/to/Bandpass/11042025

# With filter calibrations
pipenv run python -m filterbank.consolidation.consolidate \
  --filtercal-dir /path/to/filtercalibrations \
  /path/to/Bandpass/11042025
```

### Shell Scripts

Convenience scripts in `scripts/` directory:

```bash
# Consolidate a single day
bash scripts/consolidate_all.sh 11042025

# Create batch waterfall plots
bash scripts/batch_waterfall.sh 20251102
```

---

## Typical Workflow

### For Production Data (Skip Abnormal)
```bash
# 1. Preview all cycles
pipenv run python -m filterbank.consolidation.consolidate --dry-run \
  /path/to/Bandpass/11042025

# 2. Process only valid cycles
pipenv run python -m filterbank.consolidation.consolidate --skip-abnormal \
  /path/to/Bandpass/11042025

# 3. If you need day-boundary cycles too
pipenv run python -m filterbank.consolidation.consolidate --skip-abnormal --include-partial \
  /path/to/Bandpass/11042025
```

### For Complete Archive (Include Everything)
```bash
# Process all cycles regardless of validity
pipenv run python -m filterbank.consolidation.consolidate \
  /path/to/Bandpass/11042025
```

### Validation

```bash
# Validate consolidated data
pipenv run python -m filterbank.consolidation.validate \
  --consolidated-dir /path/to/Bandpass_consolidated \
  --original-dir /path/to/Bandpass/11042025
```

### Add Filter Calibrations

```bash
# Find and copy matching filter calibration files to each cycle
pipenv run python -m filterbank.consolidation.calibration \
  --consolidated-dir /path/to/Bandpass_consolidated \
  --filtercal-dir /path/to/filtercalibrations \
  --dry-run  # Preview first
```

---

## Visualization Tools

### Waterfall Plots

```bash
# Create waterfall plot for state 1
pipenv run python -m filterbank.visualization.waterfall \
  /path/to/Bandpass_consolidated/20251104 \
  --state 1

# Plot only filter 10
pipenv run python -m filterbank.visualization.waterfall \
  /path/to/Bandpass_consolidated/20251104 \
  --state 1 --filter 10

# With frequency range
pipenv run python -m filterbank.visualization.waterfall \
  /path/to/Bandpass_consolidated/20251104 \
  --state 1 --freq-range 50 200
```

### Historical Data Viewer (Web Dashboard)

```bash
# Launch web-based viewer for raw data + calibrations
pipenv run python -m filterbank.visualization.historical \
  --data-dir /path/to/Bandpass \
  --calib-dir /path/to/filtercalibrations
```

Visit http://localhost:8050 in your browser.

### Single Spectrum Plotting

```bash
# Plot a single spectrum for debugging
pipenv run python -m filterbank.visualization.single_spectrum \
  /path/to/state_file.fits \
  --spectrum-idx 0 \
  --filter 10
```

---

## Analysis Tools

### Deviation Analysis

Compare spectra against a reference to detect anomalies:

```bash
# Analyze all spectra from a day against a reference
pipenv run python -m filterbank.analysis.deviations \
  /path/to/Bandpass_consolidated/20251104 \
  --state 1 \
  --filter 10 \
  --reference-spectrum cycle_001:0
```

### Interactive Spectrum Inspector

Browse spectra across cycles with visual quality checks:

```bash
# Launch interactive inspector
pipenv run python tools/interactive_inspector.py \
  /path/to/Bandpass_consolidated/20251104 \
  --state 2 \
  --filter 10 \
  --reference-spectrum cycle_001:0
```

Use arrow keys to navigate between cycles.

---

## Performance Notes

- **Consolidation speed:** ~200-300 spectra per second
- **File size reduction:** ~2-3× (from separate files to consolidated FITS)
- **Access speed:** Binary table format allows fast random access to any spectrum
- **Real-time capable:** Can write new rows to FITS files incrementally during data collection

---

## Troubleshooting

### No Cycles Found
- Check that input directory contains `.fits` files
- Verify files follow naming convention: `MMDDYYYY_HHMMSS.fits`
- Run with `--verbose` flag for detailed output

### Cycle Count Mismatch
- Use `--dry-run` first to see detected cycles
- Check boundary times - cycles may span midnight
- Adjust `--min-spectra` and `--max-spectra` thresholds if needed

### Memory Issues with Large Datasets
- Process one day at a time instead of entire month
- Use `--cycles` flag to process specific cycles only

---

## Module Reference

### `consolidate.py`
- `CycleDetector`: Detects state sequences in spectrum files
- `ConsolidatedWriter`: Writes consolidated FITS files
- Main consolidation function

### `calibration.py`
- `find_closest_filtercals()`: Locates matching calibration files
- `apply_calibrations()`: Applies per-filter calibration corrections
- Filter calibration using 0dBm and -9dBm reference measurements

### `validate.py`
- `validate_day()`: Validates consolidated data
- `validate_consolidated_state()`: Checks individual state file
- Verifies metadata, dimensions, and value ranges
