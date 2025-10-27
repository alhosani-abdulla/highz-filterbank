#!/usr/bin/env python3
"""
Real-time Spectrometer Dashboard
Web-based viewer for High-Z Filterbank data using Plotly Dash
Access via: http://[raspberry-pi-ip]:8050
"""

import os
import glob
from pathlib import Path
import numpy as np
from astropy.io import fits
from dash import Dash, dcc, html, Input, Output
import plotly.graph_objs as go
from datetime import datetime
import calibration_utils as cal

# Configuration
DATA_DIR = "/media/peterson/INDURANCE/Data"
CALIB_DIR = "/media/peterson/INDURANCE/FilterCalibrations"
S21_DIR = "/home/peterson/highz/highz-filterbank/characterization/s_parameters"
UPDATE_INTERVAL = 2000  # milliseconds (2 seconds)

# Initialize Dash app
app = Dash(__name__)
app.title = "High-Z Filterbank Viewer"

# Layout
app.layout = html.Div([
    html.Div([
        html.H1("High-Z Filterbank Real-Time Spectrum", 
                style={'textAlign': 'center', 'color': '#2c3e50'}),
        html.Div(id='status-info', 
                style={'textAlign': 'center', 'fontSize': '14px', 'color': '#7f8c8d'}),
    ], style={'marginBottom': '20px'}),
    
    dcc.Graph(id='voltage-plot', style={'height': '40vh'}),
    dcc.Graph(id='power-plot', style={'height': '40vh'}),
    
    html.Div([
        html.Button('Pause', id='pause-button', n_clicks=0,
                   style={'marginRight': '10px', 'padding': '10px 20px'}),
        html.Span(id='pause-status', style={'marginLeft': '10px', 'fontSize': '14px'}),
    ], style={'textAlign': 'center', 'marginTop': '20px'}),
    
    dcc.Interval(
        id='interval-component',
        interval=UPDATE_INTERVAL,
        n_intervals=0
    ),
    
    # Store for pause state
    dcc.Store(id='paused', data=False),
    dcc.Store(id='paused-file', data=None),
])


def get_latest_file(directory, pattern="*.fits"):
    """Get the most recent FITS file from directory"""
    files = glob.glob(os.path.join(directory, pattern))
    if not files:
        return None
    # Filter out empty files
    files = [f for f in files if os.path.getsize(f) > 0]
    if not files:
        return None
    # Sort by modification time, get most recent
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]


def load_s2p_file(filename):
    """
    Load S2P (Touchstone) file and extract S21 magnitude in dB
    
    Args:
        filename: Path to .s2p file
        
    Returns:
        tuple: (frequencies_MHz, S21_dB) or (None, None) if error
    """
    try:
        freqs = []
        s21_db = []
        
        with open(filename, 'r') as f:
            for line in f:
                line = line.strip()
                
                # Skip comments and option lines
                if line.startswith('!') or line.startswith('#'):
                    continue
                
                # Skip empty lines
                if not line:
                    continue
                
                # Parse data line: freq S11mag S11ang S21mag S21ang S12mag S12ang S22mag S22ang
                parts = line.split()
                if len(parts) >= 5:  # Need at least freq + S11 + S21
                    try:
                        freq_hz = float(parts[0])
                        freq_mhz = freq_hz / 1e6  # Convert Hz to MHz
                        s21_mag_db = float(parts[3])  # S21 magnitude (assuming dB format)
                        
                        freqs.append(freq_mhz)
                        s21_db.append(s21_mag_db)
                    except ValueError:
                        continue
        
        if len(freqs) > 0:
            return np.array(freqs), np.array(s21_db)
        else:
            return None, None
            
    except Exception as e:
        print(f"Error loading S2P file {filename}: {e}")
        return None, None


def load_s21_corrections():
    """
    Load S21 correction data for all filters
    
    Expects files named: filter_00.s2p, filter_01.s2p, ..., filter_20.s2p
    
    Returns:
        dict: {filter_num: {'freqs': array, 's21_db': array}}
    """
    if not os.path.exists(S21_DIR):
        print(f"S21 directory not found: {S21_DIR}")
        return None
    
    s21_data = {}
    
    for filt_num in range(21):
        # Look for S21 file for this filter
        s2p_file = os.path.join(S21_DIR, f"filter_{filt_num:02d}.s2p")
        
        if not os.path.exists(s2p_file):
            print(f"Warning: S21 file not found for filter {filt_num}: {s2p_file}")
            continue
        
        freqs, s21_db = load_s2p_file(s2p_file)
        
        if freqs is not None:
            s21_data[filt_num] = {
                'freqs': freqs,
                's21_db': s21_db
            }
            print(f"Loaded S21 for filter {filt_num}: {len(freqs)} points, "
                  f"range {freqs[0]:.1f}-{freqs[-1]:.1f} MHz, "
                  f"loss {s21_db.mean():.1f} dB avg")
        else:
            print(f"Warning: Failed to parse S21 file for filter {filt_num}")
    
    if len(s21_data) == 0:
        print("No S21 files loaded")
        return None
    
    print(f"Loaded S21 corrections for {len(s21_data)}/21 filters")
    return s21_data


def get_per_filter_calibration():
    """
    Load both calibration files and create per-filter linear calibration curves.
    
    Returns:
        dict: {filter_num: {'slope': m, 'intercept': b}} for power = m*voltage + b
              Returns None if calibration files not found or invalid
    """
    try:
        # Get all calibration files
        cal_files = glob.glob(os.path.join(CALIB_DIR, "*.fits"))
        cal_files = [f for f in cal_files if os.path.getsize(f) > 0]  # Filter empty files
        
        if len(cal_files) < 2:
            print(f"Not enough calibration files found (need 2, found {len(cal_files)})")
            return None
        
        # Find the two most recent calibration files (one -4dBm, one +5dBm)
        cal_files.sort(key=os.path.getmtime, reverse=True)
        
        low_power_file = None
        high_power_file = None
        
        for f in cal_files:
            if "-4" in os.path.basename(f) and low_power_file is None:
                low_power_file = f
            elif "+5" in os.path.basename(f) and high_power_file is None:
                high_power_file = f
            if low_power_file and high_power_file:
                break
        
        if not low_power_file or not high_power_file:
            print("Could not find both -4dBm and +5dBm calibration files")
            return None
        
        # Power levels (actual measured output from LO)
        low_power_dbm = -25.0   # -4dBm setting = ~-10dBm actual
        high_power_dbm = -16.0   # +5dBm setting = ~-1dBm actual
        
        # Load S21 corrections if available
        s21_corrections = load_s21_corrections()
        
        # Filter center frequencies (MHz)
        filter_centers = [904.0 + i * 2.6 for i in range(21)]
        
        # Load calibration data
        with fits.open(low_power_file) as hdul:
            low_data = hdul[1].data
        
        with fits.open(high_power_file) as hdul:
            high_data = hdul[1].data
        
        # Build per-filter calibration curves
        filter_calibrations = {}
        
        for filt_num in range(21):
            center_freq = filter_centers[filt_num]
            
            # Find voltage at center frequency for this filter in both calibration files
            low_voltage = None
            high_voltage = None
            
            # Search through low power calibration
            # Find the LO frequency closest to this filter's center
            # When LO = center_freq, the filter sees its passband signal
            best_lo_low = None
            best_dist_low = float('inf')
            
            for row in low_data:
                lo_freq = int(float(row[5]))
                dist = abs(lo_freq - center_freq)
                if dist < best_dist_low:
                    best_dist_low = dist
                    best_lo_low = row
            
            if best_lo_low is not None and best_dist_low < 1.0:  # Within 1 MHz
                a1 = best_lo_low[0][:7]
                a2 = best_lo_low[1][:7]
                a3 = best_lo_low[2][:7]
                combined_ints = cal.makeSingleListOfInts(a1, a2, a3)
                volts = cal.toVolts(combined_ints)
                low_voltage = volts[filt_num]
            
            # Search through high power calibration
            best_lo_high = None
            best_dist_high = float('inf')
            
            for row in high_data:
                lo_freq = int(float(row[5]))
                dist = abs(lo_freq - center_freq)
                if dist < best_dist_high:
                    best_dist_high = dist
                    best_lo_high = row
            
            if best_lo_high is not None and best_dist_high < 1.0:  # Within 1 MHz
                a1 = best_lo_high[0][:7]
                a2 = best_lo_high[1][:7]
                a3 = best_lo_high[2][:7]
                combined_ints = cal.makeSingleListOfInts(a1, a2, a3)
                volts = cal.toVolts(combined_ints)
                high_voltage = volts[filt_num]
            
            if low_voltage is None or high_voltage is None:
                print(f"Warning: Could not find calibration voltages for filter {filt_num} at {center_freq:.1f} MHz")
                continue
            
            # Apply S21 correction if available
            # S21 correction adjusts the power level at the detector
            s21_loss_db = 0.0  # Default: no correction
            
            if s21_corrections and filt_num in s21_corrections:
                # Interpolate S21 at the center frequency
                s21_freqs = s21_corrections[filt_num]['freqs']
                s21_db = s21_corrections[filt_num]['s21_db']
                
                # Use numpy interpolation
                s21_loss_db = np.interp(center_freq, s21_freqs, s21_db)
                # s21_loss_db is negative (e.g., -15 dB)
            
            # Adjust power levels for S21 loss
            # Power at detector = Power at LO + S21 (in dB)
            low_power_at_detector = low_power_dbm + s21_loss_db
            high_power_at_detector = high_power_dbm + s21_loss_db
            
            # Calculate linear calibration: power = slope * voltage + intercept
            # Two points: (low_voltage, low_power_at_detector) and (high_voltage, high_power_at_detector)
            voltage_diff = high_voltage - low_voltage
            
            if abs(voltage_diff) < 0.001:  # Avoid division by zero
                print(f"Warning: No voltage difference for filter {filt_num}, skipping")
                continue
            
            slope = (high_power_at_detector - low_power_at_detector) / voltage_diff
            intercept = low_power_at_detector - slope * low_voltage
            
            filter_calibrations[filt_num] = {
                'slope': slope,
                'intercept': intercept,
                'low_v': low_voltage,
                'high_v': high_voltage,
                'center_freq': center_freq,
                's21_db': s21_loss_db  # Store for reference
            }
            
            s21_str = f", S21={s21_loss_db:.1f}dB" if s21_loss_db != 0 else ""
            print(f"Filter {filt_num} ({center_freq:.1f} MHz): "
                  f"V=[{low_voltage:.3f}, {high_voltage:.3f}] -> "
                  f"P=[{low_power_at_detector:.1f}, {high_power_at_detector:.1f}] dBm{s21_str}, "
                  f"slope={slope:.2f}")
        
        if len(filter_calibrations) < 21:
            print(f"Warning: Only calibrated {len(filter_calibrations)}/21 filters")
        
        return filter_calibrations
        
    except Exception as e:
        print(f"Error loading per-filter calibration: {e}")
        import traceback
        traceback.print_exc()
        return None


def process_spectrum_data(filename, filter_cal):
    """
    Read FITS file and process all sweeps into spectrum data
    
    Args:
        filename: Path to FITS data file
        filter_cal: Per-filter calibration dict from get_per_filter_calibration()
    
    Returns: frequencies, voltages, powers, filters, metadata
    """
    try:
        hdul = fits.open(filename)
        data = hdul[1].data
        sys_voltage = hdul[1].header.get('SYSVOLT', 0.0)
        hdul.close()
        
        if len(data) == 0:
            return None, None, None, None
        
        # Get metadata from first row
        first_state = data[0][4]  # STATE column
        
        # Process all sweeps
        all_frequencies = []
        all_voltages = []  # Raw voltages
        all_powers = []     # Calibrated powers
        all_filters = []    # Filter channel numbers (0-20)
        
        for sweep_idx in range(len(data)):
            a1 = data[sweep_idx][0][:7]  # ADHAT_1
            a2 = data[sweep_idx][1][:7]  # ADHAT_2
            a3 = data[sweep_idx][2][:7]  # ADHAT_3
            lo_freq = int(float(data[sweep_idx][5]))  # FREQUENCY
            
            # Combine ADC data
            combined_ints = cal.makeSingleListOfInts(a1, a2, a3)
            volts_data = cal.toVolts(combined_ints)
            
            # Apply per-filter calibration
            db_data = []
            for filt_num, voltage in enumerate(volts_data):
                if filter_cal and filt_num in filter_cal:
                    # Use per-filter linear calibration: power = slope * voltage + intercept
                    slope = filter_cal[filt_num]['slope']
                    intercept = filter_cal[filt_num]['intercept']
                    power = slope * voltage + intercept
                else:
                    # Fallback: simple conversion (old method)
                    power = -43.5 * voltage + 24.98
                
                db_data.append(power)
            
            # Calculate adjusted frequency axis (21 filter channels)
            frequencies = [2.6 * x + 904 - lo_freq for x in range(21)]
            filter_channels = list(range(21))
            
            all_frequencies.extend(frequencies)
            all_voltages.extend(volts_data)
            all_powers.extend(db_data)
            all_filters.extend(filter_channels)
        
        metadata = {
            'voltage': sys_voltage,
            'state': first_state,
            'num_sweeps': len(data),
            'filename': os.path.basename(filename),
            'timestamp': datetime.fromtimestamp(os.path.getmtime(filename)).strftime('%Y-%m-%d %H:%M:%S')
        }
        
        return all_frequencies, all_voltages, all_powers, all_filters, metadata
        
    except Exception as e:
        print(f"Error processing file {filename}: {e}")
        return None, None, None, None, None


@app.callback(
    [Output('paused', 'data'),
     Output('pause-button', 'children')],
    [Input('pause-button', 'n_clicks')],
    [Input('paused', 'data')]
)
def toggle_pause(n_clicks, paused):
    """Toggle pause state"""
    if n_clicks > 0:
        paused = not paused
    button_text = 'Resume' if paused else 'Pause'
    return paused, button_text


@app.callback(
    Output('paused-file', 'data'),
    [Input('interval-component', 'n_intervals')],
    [Input('paused', 'data'),
     Input('paused-file', 'data')]
)
def update_paused_file(n, paused, paused_file):
    """Store the current file when paused"""
    if paused and paused_file is None:
        # Just paused, store current file
        return get_latest_file(DATA_DIR)
    elif not paused:
        # Not paused, clear stored file
        return None
    return paused_file


@app.callback(
    [Output('voltage-plot', 'figure'),
     Output('power-plot', 'figure'),
     Output('status-info', 'children'),
     Output('pause-status', 'children')],
    [Input('interval-component', 'n_intervals')],
    [Input('paused', 'data'),
     Input('paused-file', 'data')]
)
def update_graph(n, paused, paused_file):
    """Update both voltage and power plots"""
    
    # Determine which file to display
    if paused and paused_file:
        data_file = paused_file
        status_prefix = "PAUSED - "
    else:
        data_file = get_latest_file(DATA_DIR)
        status_prefix = ""
    
    if not data_file:
        # No data available
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title="Waiting for data...",
            xaxis_title="Frequency (MHz)",
            yaxis_title="Value",
            template="plotly_white"
        )
        return empty_fig, empty_fig, "No data files found", ""
    
    # Load per-filter calibration
    filter_cal = get_per_filter_calibration()
    
    # Process spectrum data
    result = process_spectrum_data(data_file, filter_cal)
    
    if result[0] is None:
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title="Error reading data",
            template="plotly_white"
        )
        return empty_fig, empty_fig, "Error processing data file", ""
    
    frequencies, voltages, powers, filters, metadata = result
    
    # Create color palette for 21 filters using Plotly qualitative colors
    # Combine multiple palettes to get 21 distinct colors
    from plotly.colors import qualitative
    colors = (qualitative.Dark24[:21] if len(qualitative.Dark24) >= 21 
              else qualitative.Dark24 + qualitative.Light24[:21-len(qualitative.Dark24)])
    
    # Organize data by filter channel
    filter_data = {}
    for freq, volt, power, filt in zip(frequencies, voltages, powers, filters):
        if filt not in filter_data:
            filter_data[filt] = {'freq': [], 'volt': [], 'power': []}
        filter_data[filt]['freq'].append(freq)
        filter_data[filt]['volt'].append(volt)
        filter_data[filt]['power'].append(power)
    
    # Create voltage plot with separate trace for each filter
    voltage_fig = go.Figure()
    for filt_num in range(21):
        if filt_num in filter_data:
            voltage_fig.add_trace(go.Scatter(
                x=filter_data[filt_num]['freq'],
                y=filter_data[filt_num]['volt'],
                mode='markers',
                marker=dict(size=6, color=colors[filt_num]),
                name=f'Filter {filt_num}',
                showlegend=False,
                hovertemplate=f'<b>Filter {filt_num}</b><br>' +
                              '<b>Freq</b>: %{x:.1f} MHz<br>' +
                              '<b>Voltage</b>: %{y:.4f} V<br>' +
                              '<extra></extra>'
            ))
    
    voltage_fig.update_layout(
        title=f"Raw Detector Voltages - {metadata['timestamp']}",
        xaxis_title="Frequency (MHz)",
        yaxis_title="Voltage (V)",
        xaxis_range=[50, 250],
        yaxis_range=[0.5, 2.5],
        template="plotly_white",
        hovermode='closest',
        showlegend=False,
        height=400,
        uirevision='voltage'  # Preserve zoom/pan state across updates
    )
    
    # Create power plot with separate trace for each filter
    power_fig = go.Figure()
    for filt_num in range(21):
        if filt_num in filter_data:
            power_fig.add_trace(go.Scatter(
                x=filter_data[filt_num]['freq'],
                y=filter_data[filt_num]['power'],
                mode='markers',
                marker=dict(size=6, color=colors[filt_num]),
                name=f'Filter {filt_num}',
                showlegend=False,
                hovertemplate=f'<b>Filter {filt_num}</b><br>' +
                              '<b>Freq</b>: %{x:.1f} MHz<br>' +
                              '<b>Power</b>: %{y:.2f} dBm<br>' +
                              '<extra></extra>'
            ))
    
    power_fig.update_layout(
        title=f"Calibrated Power Spectrum - {metadata['timestamp']}",
        xaxis_title="Frequency (MHz)",
        yaxis_title="Power (dBm)",
        yaxis_range=[-80, 0],
        xaxis_range=[50, 250],
        template="plotly_white",
        hovermode='closest',
        showlegend=False,
        height=400,
        uirevision='power'  # Preserve zoom/pan state across updates
    )
    
    # Status information
    if filter_cal:
        num_calibrated = len(filter_cal)
        # Check how many have S21 correction
        num_with_s21 = sum(1 for f in filter_cal.values() if f.get('s21_db', 0) != 0)
        
        if num_with_s21 > 0:
            cal_status = f"✓ Per-filter cal ({num_calibrated}/21) + S21 correction ({num_with_s21}/21)"
        else:
            cal_status = f"✓ Per-filter calibration ({num_calibrated}/21)"
    else:
        cal_status = "⚠ No calibration (using fallback)"
    
    status_text = (f"{status_prefix}File: {metadata['filename']} | "
                   f"Voltage: {metadata['voltage']:.2f} V | "
                   f"State: {metadata['state']} | "
                   f"Sweeps: {metadata['num_sweeps']} | "
                   f"{cal_status}")
    
    pause_status = "⏸ PAUSED" if paused else "▶ Live"
    
    return voltage_fig, power_fig, status_text, pause_status


if __name__ == '__main__':
    print("\n" + "="*60)
    print("High-Z Filterbank Real-Time Viewer")
    print("="*60)
    print(f"\nData directory: {DATA_DIR}")
    print(f"Calibration directory: {CALIB_DIR}")
    print(f"Update interval: {UPDATE_INTERVAL/1000} seconds")
    print("\nStarting server...")
    print("\nAccess the dashboard at:")
    print("  http://localhost:8050")
    print("  http://[raspberry-pi-ip]:8050")
    print("\nPress Ctrl+C to stop")
    print("="*60 + "\n")
    
    # Run server
    # host='0.0.0.0' makes it accessible from other devices on network
    app.run(debug=False, host='0.0.0.0', port=8050)
