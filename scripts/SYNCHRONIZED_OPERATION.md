# Synchronized Spectrometer Operation

## Overview

This system coordinates two measurement programs that **cannot run simultaneously** (they share ADC hardware):

1. **Continuous Data Acquisition** (`bin/acq`) - Runs on all states, collects frequency sweeps
2. **Filter Sweep Calibration** (`bin/calib`) - Runs only on state 2 after acq finishes

The programs are synchronized using the system `state` value and a sweep counter in the acq program.

## State Sequence

The RF switch cycles through states in this order:

```
2 → 3 → 4 → 5 → 6 → 7 → 1 → 0 → 1 (antenna) → [repeat]
↑                             ↑        ↑
Calib target            Open Cal   Observing
(~40-50s)                (~15s)    (minutes)
```

**State Meanings:**
- **State 2**: Lowest signal calibrator - **TARGET for both acq and calib**
- **States 0, 3-7**: Other calibrators (acq only)
- **State 1** (first): Open circuit calibrator (acq only)
- **State 1** (second): Antenna observing state (acq only, long duration)

## Operation

### Quick Start

```bash
cd /home/peterson/highz/highz-filterbank
./scripts/run_synchronized_sweep.sh
```

Press `Ctrl+C` to stop the synchronized operation.

### How It Works

**On States 0, 1, 3-7 (Non-state-2):**
- `bin/acq` runs continuously collecting frequency sweeps
- Data saved to `/home/peterson/Continuous_Sweep/`
- Each state lasts ~15 seconds (except antenna state 1 which lasts minutes)

**On State 2 (Special handling):**
1. `bin/acq` detects state 2 and begins counting sweeps
2. ACQ collects `STATE2_MAX_SWEEPS` frequency sweeps (~10 seconds)
3. ACQ prints: "STATE 2: Collected N sweeps - Transitioning to filter calibration"
4. ACQ exits gracefully with exit code 0
5. Script launches `bin/calib` (requires sudo for GPIO)
6. CALIB performs full filter sweep (~20-30 seconds depending on delays)
7. CALIB exits when complete
8. Script restarts ACQ which resumes on whatever state is current (likely state 3)

**State 2 Duration Requirement:**
- State 2 needs to be extended to **~40-50 seconds** total
- This allows ACQ to collect data (~10s) + CALIB to run (~20-30s)
- Configure this on your external digital spectrometer

## Configuration

### Adjust State 2 Sweep Count

Edit `src/data_aquisition/ADHAT_c_subroutine_NO_SOCKET.c`:

```c
const int STATE2_MAX_SWEEPS = 3;   // Number of sweeps to collect on state 2
```

- Each sweep takes ~3-4 seconds
- `STATE2_MAX_SWEEPS = 3` → ~10 seconds of ACQ data collection on state 2
- Adjust based on your state 2 duration and calib speed

### Adjust Script Parameters

Edit `scripts/run_synchronized_sweep.sh`:

```bash
NROWS=101          # Buffer size for continuous acquisition
START_FREQ=648     # Start frequency (MHz)
END_FREQ=850       # End frequency (MHz)
```

### Adjust State 2 Duration (External Spectrometer)

Configure your external digital spectrometer to extend state 2 duration to ~40-50 seconds:
- ACQ collection: ~10 seconds
- Transition time: ~2-5 seconds
- CALIB runtime: ~20-30 seconds

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

**Issue:** ACQ exits too quickly on state 2 (not enough data collected)
- Check `STATE2_MAX_SWEEPS` value in source code
- Recompile: `make clean && make`
- Monitor output: "STATE 2 DETECTED - Collecting sweep N/M"

**Issue:** ACQ doesn't exit on state 2
- Verify state is being read correctly (check log output)
- Verify sweep counter is incrementing
- Check that ADC channels 7-9 on HAT 12 are connected

**Issue:** CALIB starts before ACQ finishes  
- This should not happen with the current design
- ACQ must exit before script proceeds to CALIB
- Check exit codes in script output

**Issue:** State transitions before CALIB completes
- State 2 duration is too short
- Extend state 2 duration on external spectrometer to 40-50 seconds
- Or reduce CALIB delays/speed up calibration sweep

**Issue:** Programs conflict or hang
- Verify only ONE program runs at a time
- Check for zombie processes: `ps aux | grep -E "(acq|calib)"`
- Kill if needed: `pkill -9 acq; pkill -9 calib`

## Manual Operation

You can run each program individually for testing:

```bash
# Continuous acquisition
./bin/acq 101 648 850

# Filter sweep calibration
sudo ./bin/calib
```
