# High-Z Filterbank Real-Time Dashboard

Modern web-based viewer for spectrometer data. No X11 forwarding required!

## Features

- ✅ **Interactive plots** - Zoom, pan, hover to see exact values
- ✅ **Real-time updates** - New data every 2 seconds
- ✅ **Pause/Resume** - Freeze on interesting spectra
- ✅ **Automatic calibration** - Uses latest calibration file
- ✅ **Network accessible** - View from any device on your network
- ✅ **Works offline** - No internet connection needed
- ✅ **Clean, modern UI** - Web-based interface

## Quick Start

### 1. Install Dependencies

**Easy way (recommended):**
```bash
cd /home/peterson/highz/highz-filterbank/tools/rtviewer
./setup_dashboard.sh
```

This script will:
- Install system packages (python3-venv) if needed
- Create a virtual environment
- Install all Python dependencies (dash, plotly, numpy, astropy)
- Create a launcher script

**Manual way:**
```bash
cd /home/peterson/highz/highz-filterbank/tools/rtviewer
python3 -m venv venv
source venv/bin/activate
pip install numpy astropy dash plotly
```

### 2. Run the Dashboard

**Using the launcher:**
```bash
cd /home/peterson/highz/highz-filterbank/tools/rtviewer
./run_dashboard.sh
```

**Or manually:**
```bash
cd /home/peterson/highz/highz-filterbank/tools/rtviewer
source venv/bin/activate
python3 dashboard.py
```

### 3. Access in Browser

**On the Raspberry Pi:**
- Open browser to: `http://localhost:8050`

**From your Mac (or any device on the network):**
- Find Pi's IP address: `hostname -I` on Pi
- Open browser to: `http://[pi-ip-address]:8050`
- Example: `http://192.168.1.100:8050`

**In VS Code:**
- Use Command Palette (Cmd+Shift+P)
- Type "Simple Browser: Show"
- Enter URL: `http://localhost:8050` (if on Pi) or `http://[pi-ip]:8050`

## Usage

### Interactive Features

- **Zoom**: Click and drag to zoom into a region
- **Pan**: Hold shift and drag to pan
- **Reset**: Double-click to reset view
- **Hover**: Mouse over points to see exact frequency and power values
- **Pause/Resume**: Click the Pause button to freeze on current spectrum

### Status Bar

Shows real-time information:
- Current file being displayed
- System voltage
- Switch state
- Number of sweeps in file
- Calibration status

### Configuration

Edit `dashboard.py` to change:

```python
DATA_DIR = "/media/peterson/INDURANCE/Data"
CALIB_DIR = "/media/peterson/INDURANCE/FilterCalibrations"
UPDATE_INTERVAL = 2000  # milliseconds
```

## Advantages over X11/matplotlib

| Feature | Old (matplotlib + X11) | New (Dash) |
|---------|----------------------|------------|
| Setup | Requires X11 forwarding, XQuartz | Just open browser |
| Speed | Slow over network | Fast, optimized |
| Interactivity | Limited | Full zoom/pan/hover |
| Multi-device | One display only | Access from anywhere |
| Resource usage | High (X11 overhead) | Low (just HTTP) |
| Code quality | Complex matplotlib animation | Clean callback structure |

## Troubleshooting

### Port already in use

If port 8050 is busy, change it in the script:
```python
app.run_server(debug=False, host='0.0.0.0', port=8051)
```

### Can't connect from Mac

1. Check Pi's IP: `hostname -I`
2. Check firewall: `sudo ufw status`
3. Test connection: `ping [pi-ip]` from Mac

### No data showing

1. Verify data directory exists and has FITS files:
   ```bash
   ls -lh /media/peterson/INDURANCE/Data/*.fits
   ```

2. Check calibration directory:
   ```bash
   ls -lh /media/peterson/INDURANCE/FilterCalibrations/*.fits
   ```

### Calibration not working

The dashboard will still work without calibration, using fallback conversion. Check the status bar for "⚠ No calibration" vs "✓ Calibrated".

## Running in Background

To keep it running after closing terminal:

```bash
nohup python3 dashboard.py > dashboard.log 2>&1 &
```

To stop:
```bash
pkill -f dashboard.py
```

## Future Enhancements

Possible additions:
- Historical view (scroll through previous spectra)
- Compare multiple spectra
- Export current view as image
- Adjustable update interval
- Multiple plot views (current + previous)
- Annotation/marking features

## Files

- `dashboard.py` - Main dashboard application
- `calibration_utils.py` - Calibration utilities (shared with old viewer)
- `rtviewer.py` - Old matplotlib viewer (deprecated)

## Comparison with Old Viewer

The new dashboard completely replaces `rtviewer.py` with a better architecture:

**Old approach:**
```python
# matplotlib animation with X11 forwarding
v = anim.FuncAnimation(fig, update, ...)
plt.show()  # Requires X11
```

**New approach:**
```python
# Dash callbacks with web server
@app.callback(...)
def update_graph(n):
    return figure  # Returns data, server handles display
```

## Development

To enable debug mode (auto-reload on code changes):

```python
app.run_server(debug=True, host='0.0.0.0', port=8050)
```

Note: Debug mode is disabled by default for production use.
