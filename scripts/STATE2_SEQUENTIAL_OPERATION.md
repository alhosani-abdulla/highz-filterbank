# State 2 Sequential Operation - Quick Reference

## Problem Solved
ACQ and CALIB cannot run simultaneously (they share ADC hardware). The system needed to run them **sequentially** on state 2.

## Solution Implemented

### Changes Made

1. **`src/data_aquisition/continuous_acq.c`**
   - Added `state2_sweeps_collected` counter and `STATE2_MAX_SWEEPS` constant (default: 3)
   - Modified state 2 detection logic:
     - OLD: Immediately exit when state 2 detected (no data collected)
     - NEW: Collect `STATE2_MAX_SWEEPS` sweeps on state 2, THEN exit
   - This gives ~10 seconds of ACQ data on state 2 before transitioning

2. **`scripts/run_synchronized_sweep.sh`**
   - Already correct: runs ACQ, waits for exit, then runs CALIB
   - Updated documentation to explain sequential operation

3. **`scripts/SYNCHRONIZED_OPERATION.md`**
   - Updated to reflect sequential operation model
   - Added configuration instructions
   - Added timing requirements

## How It Works Now

```
State 2 begins (~40-50 seconds total required)
├─ ACQ starts/continues running
├─ ACQ detects state 2
├─ ACQ collects 3 frequency sweeps (~10 seconds)
│  └─ Prints: "STATE 2 DETECTED - Collecting sweep 1/3"
│  └─ Prints: "STATE 2 DETECTED - Collecting sweep 2/3"
│  └─ Prints: "STATE 2 DETECTED - Collecting sweep 3/3"
├─ ACQ prints: "STATE 2: Collected 3 sweeps - Transitioning to filter calibration"
├─ ACQ exits gracefully (exit code 0)
├─ Script detects ACQ exit
├─ Script waits 2 seconds
├─ Script starts CALIB
├─ CALIB runs full sweep (~20-30 seconds)
├─ CALIB exits when complete
├─ Script waits 5 seconds
└─ Script restarts ACQ (now on state 3 or whatever is current)
```

## Configuration

### Adjust Number of Sweeps on State 2

Edit `src/data_aquisition/continuous_acq.c`:

```c
const int STATE2_MAX_SWEEPS = 3;   // Change this number
```

Then rebuild:
```bash
cd /home/peterson/highz/highz-filterbank
make clean
make
```

**Sweep timing:**
- Each sweep: ~3-4 seconds
- 3 sweeps = ~10 seconds
- 5 sweeps = ~15-20 seconds

### Adjust State 2 Duration (External Spectrometer)

Required state 2 duration:
```
STATE2_DURATION = (STATE2_MAX_SWEEPS × 3-4 sec) + 5 sec + CALIB_TIME

Example with defaults:
= (3 × 3.5 sec) + 5 sec + 25 sec
= 10.5 + 5 + 25
= ~40-45 seconds
```

Configure this on your external digital spectrometer that controls the RF switch.

## Testing

### Quick Test
```bash
# Run the synchronized script
cd /home/peterson/highz/highz-filterbank
./scripts/run_synchronized_sweep.sh
```

Watch for these messages when state 2 appears:
```
STATE 2 DETECTED - Collecting sweep 1/3
STATE 2 DETECTED - Collecting sweep 2/3
STATE 2 DETECTED - Collecting sweep 3/3
STATE 2: Collected 3 sweeps - Transitioning to filter calibration
Continuous acquisition ended (exit code: 0)
Phase 2: Filter Sweep Calibration
```

### Verify Sequential Operation

1. State 2 begins
2. ACQ prints "STATE 2 DETECTED" messages
3. ACQ exits (NOT killed)
4. CALIB starts (ACQ is no longer running)
5. CALIB completes
6. ACQ restarts on next state

You should NEVER see both programs running at the same time.

### Check Process Count

In another terminal while running:
```bash
# Should only show ONE of these at a time
ps aux | grep -E "(bin/acq|bin/calib)" | grep -v grep
```

## Troubleshooting

### ACQ exits immediately on state 2 (like old behavior)
- You didn't recompile after changing the code
- Solution: `make clean && make`

### ACQ never exits on state 2
- State is not being detected correctly
- Check output for "Pin 7,8,9: ADC value..." messages
- Verify connections to HAT 12 channels 7-9

### State transitions before CALIB completes
- State 2 duration too short on external spectrometer
- Need to extend state 2 to ~40-50 seconds
- OR reduce CALIB delays to speed it up

### Both programs running at same time
- This should be impossible with current script
- Script waits for ACQ to exit before starting CALIB
- Check for zombie processes: `pkill -9 acq; pkill -9 calib`

## Output Files

### ACQ Files
Location: `/home/peterson/Continuous_Sweep/`

State 2 files will now contain actual data:
- ADHAT_1, ADHAT_2, ADHAT_3: ADC readings
- STATE column: "2" 
- Multiple rows from state 2 (3 × 101 = 303 rows per sweep cycle)

### CALIB Files  
Location: `/home/peterson/FilterCalibrations/`

Format: `MMDDYYYY_HHMMSS_+5dBm.fits` and `MMDDYYYY_HHMMSS_-4dBm.fits`

## Field Deployment Checklist

- [ ] Recompile after setting desired `STATE2_MAX_SWEEPS`: `make clean && make`
- [ ] Test script manually for one full state cycle
- [ ] Verify ACQ collects data on state 2 (check FITS files)
- [ ] Verify CALIB runs after ACQ exits
- [ ] Time the complete state 2 cycle (ACQ + transition + CALIB)
- [ ] Configure external spectrometer state 2 duration accordingly
- [ ] Run for several cycles to verify stability
- [ ] Monitor output and FITS files to confirm correct operation

## State Timing Reference

```
State 0:  ~15 sec  (ACQ only)
State 1:  ~15 sec  (ACQ only, open cal)
State 2:  ~45 sec  (ACQ 10s + CALIB 30s) ← EXTENDED
State 3:  ~15 sec  (ACQ only)
State 4:  ~15 sec  (ACQ only)
State 5:  ~15 sec  (ACQ only)
State 6:  ~15 sec  (ACQ only)
State 7:  ~15 sec  (ACQ only)
State 1:  3+ min   (ACQ only, antenna observing) ← LONG
[cycle repeats]
```

Total calibration cycle: ~135 seconds (2.25 minutes)
Total with antenna: 3-5 minutes per complete cycle
