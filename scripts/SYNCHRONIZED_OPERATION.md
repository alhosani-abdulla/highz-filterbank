# Synchronized Spectrometer Operation

## Overview

This system coordinates two measurement programs that run in sequence:

1. **Continuous Data Acquisition** (`bin/acq`) - Runs continuous frequency sweeps
2. **Filter Sweep Calibration** (`bin/calib`) - Performs filter bank calibration

The programs are synchronized using the system `state` value:
- When `state == 2` is detected by the continuous acquisition, it exits gracefully
- The filter sweep calibration then runs
- After calibration completes, the cycle repeats

## Operation

### Quick Start

```bash
cd /home/peterson/highz/highz-filterbank
./scripts/run_synchronized_sweep.sh
```

Press `Ctrl+C` to stop the synchronized operation.

### How It Works

**Phase 1: Continuous Acquisition**
- Runs `bin/acq` with frequency sweeps from 648-850 MHz
- Collects data from 3 AD HATs simultaneously
- Monitors system state via ADC channels 7-9 on HAT 12
- When `state == 2` is detected, exits cleanly and triggers Phase 2

**Phase 2: Filter Calibration**
- Runs `bin/calib` (requires sudo for GPIO access)
- Performs frequency sweeps from 900-960 MHz in 0.2 MHz steps
- Collects data at two power levels (+5 dBm and -4 dBm)
- Saves calibration data to `/home/peterson/FilterCalibrations/`
- Upon completion, system returns to Phase 1

**Cycle Repeats** until manually stopped with `Ctrl+C`

## Configuration

Edit `scripts/run_synchronized_sweep.sh` to modify:

```bash
NROWS=101          # Buffer size for continuous acquisition
START_FREQ=648     # Start frequency (MHz)
END_FREQ=850       # End frequency (MHz)
```

## Output Files

**Continuous Acquisition:**
- Location: `/home/peterson/Continuous_Sweep/`
- Format: `MMDDYYYY_HHMMSS.fits`
- Contains: ADC data, timestamps, switch state, frequency, system voltage

**Filter Calibration:**
- Location: `/home/peterson/FilterCalibrations/`
- Format: `MMDDYYYY_HHMMSS_+5dBm.fits` and `MMDDYYYY_HHMMSS_-4dBm.fits`
- Contains: ADC data for filter characterization at two power levels

## State Detection

The system state is encoded in 3 bits (ADC channels 7-9 on HAT 12):
- State 0: All switches off (000 binary)
- State 2: Switch on channel 8 active (010 binary)
- States 1-7: Other switch combinations

When the external control system sets state to 2, this triggers the transition to filter calibration.

## Troubleshooting

**Issue:** Continuous acquisition doesn't exit on state 2
- Check that ADC channels 7-9 are correctly connected
- Verify voltage thresholds in state calculation (value < 3 = off, >= 3 = on)

**Issue:** Filter sweep fails to start
- Ensure script has sudo access: `sudo ./scripts/run_synchronized_sweep.sh`
- Check GPIO permissions for pigpio

**Issue:** Programs don't alternate
- Check exit codes printed by the script
- Verify both binaries exist: `ls -l bin/acq bin/calib`

## Manual Operation

You can run each program individually for testing:

```bash
# Continuous acquisition
./bin/acq 101 648 850

# Filter sweep calibration
sudo ./bin/calib
```
