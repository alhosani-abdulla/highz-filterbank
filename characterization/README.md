# Hardware Characterization Data

This directory contains static characterization measurements of the High-Z Filterbank hardware. These measurements are performed once (or periodically) to characterize the RF system and are used to calibrate data processing.

## Directory Structure

```
characterization/
├── s_parameters/          # S-parameter measurements (S21, S11, etc.)
├── metadata.json          # Measurement metadata (dates, equipment, conditions)
└── README.md             # This file
```

## S-Parameters (`s_parameters/`)

### Purpose
S21 transmission measurements from the Local Oscillator (LO) output to each filter/detector input. These measurements quantify the total RF path loss including:
- Cables
- 8-way power splitter
- 4-way power splitters  
- Bandpass filters (900-960 MHz)
- All connectors and impedance mismatches

### File Naming Convention
```
filter_XX.s2p
```
Where `XX` is the filter number (00-20) for the 21 cavity filters.

**Filter Mapping:**
- Filter 00: 904.0 MHz center
- Filter 01: 906.6 MHz center
- Filter 02: 909.2 MHz center
- ...
- Filter 20: 956.0 MHz center

(2.6 MHz spacing between adjacent filters)

### Measurement Procedure

**Equipment:**
- NanoVNA or similar Vector Network Analyzer
- SMA cables and adapters

**Setup:**
1. **Calibrate VNA** at the measurement plane:
   - Port 1: At LO output connector
   - Port 2: At detector input connector (after filter)
   - Frequency range: 900-960 MHz
   - Points: 201 or more (0.3 MHz resolution or better)

2. **For each of the 21 filters:**
   - Disconnect detector from filter output
   - Connect VNA Port 2 to filter output (detector input point)
   - Connect VNA Port 1 to LO output
   - Measure S21 (transmission) across 900-960 MHz
   - Save as `filter_XX.s2p` in Touchstone format
   - Reconnect detector

3. **Record metadata** (see metadata.json template below)

### S2P File Format

Standard Touchstone format:
```
# MHz S MA R 50
! Freq[MHz]  S11[dB]  S11[deg]  S21[dB]  S21[deg]  S12[dB]  S12[deg]  S22[dB]  S22[deg]
900.0  -15.2  45.3  -18.5  -120.4  ...
```

The dashboard uses the S21 magnitude (column 4) for calibration.

### How S21 is Used

The dashboard applies S21 correction to the per-filter calibration:

1. **Load S21 data** for each filter
2. **Interpolate S21** at the measurement frequency
3. **Correct calibration points:**
   ```
   Actual_power_at_detector = LO_power_setting + S21_loss(freq)
   ```
4. **Apply corrected calibration** to convert voltage → power

This accounts for the ~10-20 dB of RF path loss and gives accurate absolute power measurements.

## Metadata Template

Create `metadata.json` with measurement details:

```json
{
  "measurement_date": "2025-10-26",
  "equipment": {
    "vna": "NanoVNA-H4",
    "cables": "SMA, <1m length",
    "calibration_kit": "SMA OSL"
  },
  "conditions": {
    "temperature_C": 22,
    "humidity_percent": 45,
    "notes": "Lab bench measurement, system at room temperature"
  },
  "measurement_parameters": {
    "start_freq_MHz": 900,
    "stop_freq_MHz": 960,
    "num_points": 201,
    "if_bandwidth_Hz": 1000,
    "power_dBm": 0
  },
  "filters": {
    "manufacturer": "Custom cavity filters",
    "bandwidth_MHz": 0.2,
    "insertion_loss_dB": "~2-3 (typical)"
  },
  "notes": "Measured end-to-end from LO output to detector input, includes all RF chain components and filters"
}
```

## Updates and Versioning

- **Initial characterization:** Measure all 21 filters
- **Re-characterization needed if:**
  - Hardware modifications (cable changes, component replacements)
  - Significant temperature changes
  - System performance degradation observed
  - Periodic validation (e.g., annually)

- **Version control:** Commit S2P files to git with descriptive commit messages
- **Date tracking:** Use git commits or metadata.json to track measurement dates

## Data Processing

The S21 data is automatically loaded by the dashboard (`tools/rtviewer/dashboard.py`) during startup. The `load_s21_data()` function reads all S2P files and interpolates them for real-time calibration.

## Quality Checks

After measurement, verify:
- [ ] All 21 S2P files present and valid
- [ ] S21 values reasonable (-15 to -25 dB typical in-band)
- [ ] Smooth frequency response (no anomalous spikes)
- [ ] Filter passbands visible in S21 curves
- [ ] Metadata.json complete and accurate
- [ ] Dashboard loads S21 data without errors

---

*For questions or updates, see project documentation or contact the maintainer.*
