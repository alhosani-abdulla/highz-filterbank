# Automated Cycle Controller

## Overview

The automated cycle controller (`bin/cycle_control`) manages continuous data acquisition cycles. It runs on startup and continuously executes the state sequence **1→2→3→4→5→6→7→0** until stopped.

## Features

- **Persistent State**: Survives restarts by maintaining state in `/media/peterson/INDURANCE/Data/.cycle_state`
- **Automatic Cycle Numbering**: Generates cycle IDs in format `Cycle_MMDDYYYY_###`
- **Day Transitions**: Handles midnight boundary crossings correctly
- **Restart Recovery**: If interrupted mid-cycle, automatically moves to next cycle
- **Metadata Generation**: Creates `cycle_metadata.json` for each cycle
- **Configurable Antenna Info**: Reads from `/media/peterson/INDURANCE/Data/.antenna_config`
- **Organized Logging**: Creates run-specific directories with controller and per-cycle child logs
- **Flexible Spectra Counts**: Different counts for calibration states (1-7) vs antenna state (0)

## Logging Structure

Each system run creates a timestamped directory containing:
- **cycle_control.log**: High-level controller flow (startup, cycle transitions, timing)
- **Cycle_MMDDYYYY_###.log**: Detailed child program output for each cycle (all acq + calib output)

```
/media/peterson/INDURANCE/Logs/
├── run_20260218_142345/
│   ├── cycle_control.log          # Controller overview
│   ├── Cycle_02182026_001.log     # All output for cycle 1
│   ├── Cycle_02182026_002.log     # All output for cycle 2
│   └── Cycle_02182026_003.log     # All output for cycle 3
└── run_20260218_180512/           # After restart
    ├── cycle_control.log
    └── Cycle_02182026_004.log
```
- **Logging**: Each run creates a timestamped logfile in `/media/peterson/INDURANCE/Logs`
- **State-Specific Spectra**: Different counts for calibration (states 1-7) vs antenna (state 0)

## Usage

```bash
sudo ./bin/cycle_control --timezone <offset> --spectra-calib <count> --spectra-antenna <count>
```

### Parameters

- `--timezone`: Timezone offset (e.g., `-07:00`, `+00:00`, `+05:30`)
- `--spectra-calib`: Number of spectra for calibration states 1-7 (typically 6-7)
- `--spectra-antenna`: Number of spectra for antenna state 0 (typically ~300)

### Examples

```bash
# Run with PST timezone, 7 spectra for calib, 300 for antenna
sudo ./bin/cycle_control --timezone -07:00 --spectra-calib 7 --spectra-antenna 300

# Run with UTC timezone, 6 spectra for calib, 250 for antenna
sudo ./bin/cycle_control --timezone +00:00 --spectra-calib 6 --spectra-antenna 250
```

## State Sequence

For each cycle, the controller executes states in this order:

1. **State 1**: Continuous acquisition (calibration, ~7 spectra)
2. **State 2**: Filter sweep calibration + continuous acquisition (calibration, ~7 spectra)
3. **State 3**: Continuous acquisition (calibration, ~7 spectra)
4. **State 4**: Continuous acquisition (calibration, ~7 spectra)
5. **State 5**: Continuous acquisition (calibration, ~7 spectra)
6. **State 6**: Continuous acquisition (calibration, ~7 spectra)
7. **State 7**: Continuous acquisition (calibration, ~7 spectra)
8. **State 0**: Continuous acquisition (antenna, ~300 spectra, cycle end)

After completing state 0, a new cycle begins at state 1.

## Logging

Each run of the cycle controller creates a timestamped logfile in `/media/peterson/INDURANCE/Logs/`:

- **Filename format**: `cycle_control_YYYYMMDD_HHMMSS.log`
- **Content**: All console output (startup info, state changes, errors)
- **Restart behavior**: New logfile created on each restart

Example logfile names:
```
cycle_control_20260218_140523.log  # Started at 14:05:23 on Feb 18, 2026
cycle_control_20260218_152314.log  # Restarted at 15:23:14
```

## Antenna Configuration

The program reads antenna/site information from `/media/peterson/INDURANCE/Data/.antenna_config`:

```ini
# Example configuration
antenna_id=Prototype_v1
site_name=Test_Site_A
notes=Initial deployment for system characterization
```

If the file doesn't exist, metadata will use "Unknown" defaults.

## Persistent State

The program maintains state in `/media/peterson/INDURANCE/Data/.cycle_state`:

```
MMDDYYYY:cycle_num:last_state
```

Example: `02182026:003:0` means cycle 3 completed on 02/18/2026.

### Restart Behavior

- **Mid-cycle restart**: Moves to next cycle number
- **Between cycles**: Continues from next cycle
- **Day transition**: Increments date, continues cycle sequence

## Output Structure

```
/media/peterson/INDURANCE/
├── Data/
│   ├── .antenna_config          # Antenna configuration
│   ├── .cycle_state            # Persistent state file
│   ├── 02182026/               # Date directory
│   │   ├── Cycle_02182026_001/
│   │   │   ├── cycle_metadata.json
│   │   │   ├── filtercal_+5dBm.fits
│   │   │   ├── filtercal_-4dBm.fits
│   │   │   ├── state_1_spectra.fits
│   │   │   ├── state_2_spectra.fits
│   │   │   ├── ...
│   │   │   └── state_0_spectra.fits
│   │   └── Cycle_02182026_002/
│   │       └── ...
└── Logs/
    ├── run_20260218_142345/      # System run directory
    │   ├── cycle_control.log     # Controller overview
    │   ├── Cycle_02182026_001.log  # All child output for cycle 1
    │   └── Cycle_02182026_002.log  # All child output for cycle 2
    └── run_20260218_180512/      # After restart
        ├── cycle_control.log
        └── Cycle_02182026_003.log
```

## Metadata File Format

Each cycle generates `cycle_metadata.json`:

```json
{
  "cycle_id": "Cycle_02182026_001",
  "start_time": "2026-02-18T14:23:45",
  "end_time": "2026-02-18T14:45:12",
  "timezone": "-07:00",
  "state_sequence": [1, 2, 3, 4, 5, 6, 7, 0],
  "spectra_calib": 7,
  "spectra_antenna": 300,
  "antenna": {
    "antenna_id": "Prototype_v1",
    "site_name": "Test_Site_A",
    "notes": "Initial deployment"
  }
}
```

## Signal Handling

The controller responds gracefully to shutdown signals:

- **SIGINT** (Ctrl+C): Completes current state, saves progress, exits
- **SIGTERM**: Same as SIGINT (for systemd/init systems)

## Stopping the Controller

Press **Ctrl+C** to initiate graceful shutdown. The program will:

1. Complete the current state acquisition
2. Save the current cycle state
3. Return GPIO to safe state (state 5)
4. Exit cleanly

## Manual State Control

For diagnostic purposes, use the manual state control tool:

```bash
sudo ./bin/state_manual [initial_state]
```

This provides interactive state control (user types state numbers 0-7).

## Troubleshooting

### Program won't start

- Check GPIO permissions: `sudo` required
- Verify pigpio is running: `sudo systemctl status pigpiod`

### State file corruption

Delete `/media/peterson/INDURANCE/Data/.cycle_state` to reset:
```bash
rm /media/peterson/INDURANCE/Data/.cycle_state
```

### Missing antenna config

Create `/media/peterson/INDURANCE/Data/.antenna_config` or accept "Unknown" defaults.

### Log files

Each system run creates a directory in `/media/peterson/INDURANCE/Logs/run_YYYYMMDD_HHMMSS/`:
- **cycle_control.log**: Controller high-level flow (startup, cycle transitions, errors)
- **Cycle_MMDDYYYY_###.log**: Detailed child program output (acq + calib) for each cycle

The controller log shows what's happening at a high level. The per-cycle logs contain all ADC readings and detailed output from the child programs.

### Day transition issues

The cycle_id embeds the date, so transitions are handled automatically.
