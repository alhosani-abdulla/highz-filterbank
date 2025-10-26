# Autostart Configuration for High-Z Filterbank

This directory contains scripts for running the synchronized sweep on system boot.

## Quick Start

### Enable Autostart

```bash
cd /home/peterson/highz/highz-filterbank/scripts
./setup_autostart.sh
```

This will:
- Make the sweep script executable
- Create the log directory `/var/log/highz-filterbank/`
- Add a crontab entry to run on boot (with 30 second delay)

### Disable Autostart

```bash
./remove_autostart.sh
```

## Monitoring

### View Live Log

```bash
tail -f /media/peterson/INDURANCE/Logs/synchronized_sweep.log
```

### Check if Running

```bash
ps aux | grep run_synchronized_sweep
```

### Stop the Sweep

```bash
pkill -f run_synchronized_sweep.sh
```

Or use Ctrl+C if running in a terminal.

## Manual Testing

Test the script manually before enabling autostart:

```bash
./run_synchronized_sweep.sh
```

This will run in the foreground and show output on the terminal.

## How It Works

### Crontab Entry

The setup script adds this line to **root's crontab** (not user crontab):

```
@reboot /home/peterson/highz/highz-filterbank/scripts/run_synchronized_sweep.sh >> /media/peterson/INDURANCE/Logs/synchronized_sweep.log 2>&1
```

- Runs as **root** (needed for GPIO access)
- `@reboot`: Runs on system startup immediately
- Output redirected to log file

### Cycle Operation

1. **ACQ Phase**: Runs continuous data acquisition (650-850 MHz)
   - Collects data until STATE 2 is detected
   - Collects STATE2_MAX_SWEEPS (3) complete sweeps on STATE 2
   - Exits gracefully

2. **CALIB Phase**: Runs filter calibration (900-960 MHz)
   - Dual power sweep: +5 dBm → -4 dBm
   - Saves two FITS files

3. **Loop**: Returns to ACQ phase and repeats

### Log Files

All output from both programs is captured in:

```
/media/peterson/INDURANCE/Logs/synchronized_sweep.log
```

Each log entry is timestamped for easy tracking.

## Troubleshooting

### Script doesn't start on boot

1. Check root crontab entry:
   ```bash
   sudo crontab -l
   ```

2. Check for errors in system log:
   ```bash
   grep CRON /var/log/syslog
   ```

3. Verify script is executable:
   ```bash
   ls -l /home/peterson/highz/highz-filterbank/scripts/run_synchronized_sweep.sh
   ```

### Permission errors

The script runs as root via crontab, so both `acq` and `calib` will have the necessary GPIO permissions.

### GPIO not initialized

The 30-second delay after boot should be sufficient for pigpio to initialize. If problems persist, increase the delay in the crontab entry.

## Files

- `run_synchronized_sweep.sh` - Main control script
- `setup_autostart.sh` - Enable autostart on boot
- `remove_autostart.sh` - Disable autostart
- `AUTOSTART_README.md` - This file

## Configuration

To modify sweep parameters, edit the source files:
- ACQ parameters: `src/data_aquisition/continuous_acq.c`
- CALIB parameters: `src/calibration/filterSweep.c`

Then recompile:
```bash
cd /home/peterson/highz/highz-filterbank
make clean && make
```
