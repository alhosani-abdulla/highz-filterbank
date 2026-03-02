#!/usr/bin/env python3
"""
Historical Filterbank Data Viewer
Web-based viewer for archived High-Z Filterbank data using Plotly Dash
Load data from any date/time and view in the same dashboard format as rtviewer
"""

import os
import glob
import argparse
from pathlib import Path
from datetime import datetime, timedelta
import numpy as np
from astropy.io import fits
from dash import Dash, dcc, html, Input, Output, State
import plotly.graph_objs as go

# Add parent paths to import calibration utilities and highz_exp modules
import sys
root_dir = Path(__file__).parent.parent.parent  # src/filterbank/visualization -> src
highz_filterbank_root = root_dir.parent.parent  # src -> Highz-EXP
sys.path.insert(0, str(root_dir))  # For highz_exp module
sys.path.insert(0, str(highz_filterbank_root / "highz-filterbank" / "tools" / "rtviewer"))
sys.path.insert(0, str(highz_filterbank_root / "highz-filterbank" / "tools" / "Plotting"))

try:
    import calibration_utils as cal
except ImportError:
    print("Warning: calibration_utils not found, will use fallback calibration")
    cal = None

# Import filter plotting utilities from local module
try:
    from highz_exp.filter_plotting import (
        load_filterbank_table, 
        adc_counts_to_voltage, 
        voltage_to_dbm
    )
    FILTER_PLOTTING_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import filter_plotting: {e}")
    FILTER_PLOTTING_AVAILABLE = False

# Configuration
DATA_BASE_DIR = "/Users/abdullaalhosani/Projects/highz/Data/LunarDryLake/2025Nov/filterbank/Bandpass"
CALIB_DIR = "/Users/abdullaalhosani/Projects/highz/Data/LunarDryLake/2025Nov/filterbank/filtercalibrations"
S21_DIR = "/Users/abdullaalhosani/Projects/highz/highz-filterbank/characterization/s_parameters"

# Correction flags (modular - easily togglable)
APPLY_S21_CORRECTIONS = True  # Apply S21 loss correction from S-parameter files
APPLY_FILTER_NORMALIZATION = True  # Normalize filter responses to align spectra (calculated from measurement data)

# Initialize Dash app
app = Dash(__name__)
app.title = "High-Z Filterbank Historical Viewer"

# Layout
app.layout = html.Div([
    html.Div([
        html.H1("High-Z Filterbank Historical Data Viewer", 
                style={'textAlign': 'center', 'color': '#2c3e50'}),
        html.Div(id='status-info', 
                style={'textAlign': 'center', 'fontSize': '14px', 'color': '#7f8c8d'}),
    ], style={'marginBottom': '20px'}),
    
    # Date/Time selector
    html.Div([
        html.Div([
            html.Label("Select Date:", style={'marginRight': '10px', 'fontWeight': 'bold'}),
            dcc.Dropdown(
                id='date-dropdown',
                placeholder='Select a date...',
                style={'width': '200px'}
            ),
        ], style={'display': 'inline-block', 'marginRight': '20px'}),
        
        html.Div([
            html.Label("Select File:", style={'marginRight': '10px', 'fontWeight': 'bold'}),
            dcc.Dropdown(
                id='file-dropdown',
                placeholder='Select a file...',
                style={'width': '400px'}
            ),
        ], style={'display': 'inline-block', 'marginRight': '20px'}),
        
        html.Button('Load', id='load-button', n_clicks=0,
                   style={'padding': '8px 20px', 'backgroundColor': '#3498db', 
                          'color': 'white', 'border': 'none', 'borderRadius': '4px',
                          'cursor': 'pointer'}),
    ], style={'padding': '15px', 'backgroundColor': '#ecf0f1', 'borderRadius': '4px',
              'marginBottom': '20px', 'display': 'flex', 'alignItems': 'center',
              'gap': '15px', 'flexWrap': 'wrap'}),
    
    # 2x2 grid layout for plots
    html.Div([
        html.Div([
            dcc.Graph(id='voltage-plot', style={'height': '100%'})
        ], style={'display': 'inline-block', 'width': '48%', 'marginRight': '2%', 'verticalAlign': 'top'}),
        
        html.Div([
            dcc.Graph(id='power-plot', style={'height': '100%'})
        ], style={'display': 'inline-block', 'width': '48%', 'verticalAlign': 'top'}),
    ], style={'marginBottom': '20px', 'height': '500px'}),
    
    html.Div([
        html.Div([
            dcc.Graph(id='calib-positive-plot', style={'height': '100%'})
        ], style={'display': 'inline-block', 'width': '48%', 'marginRight': '2%', 'verticalAlign': 'top'}),
        
        html.Div([
            dcc.Graph(id='calib-negative-plot', style={'height': '100%'})
        ], style={'display': 'inline-block', 'width': '48%', 'verticalAlign': 'top'}),
    ], style={'marginBottom': '20px', 'height': '500px'}),
    
    # Store for loaded file data
    dcc.Store(id='loaded-file-data'),
    dcc.Store(id='available-dates'),
])


def find_available_dates():
    """
    Scan DATA_BASE_DIR for available dates
    Expects structure: DATA_BASE_DIR/MMddyyyy/files (e.g., 11042025)
    """
    dates = []
    if os.path.exists(DATA_BASE_DIR):
        # Look for date folders
        for entry in os.listdir(DATA_BASE_DIR):
            path = os.path.join(DATA_BASE_DIR, entry)
            if os.path.isdir(path):
                # Try to parse as date in MMddyyyy format
                try:
                    # Format: MMddyyyy (e.g., 11042025 = Nov 4, 2025)
                    if len(entry) == 8 and entry.isdigit():
                        mm = entry[:2]
                        dd = entry[2:4]
                        yyyy = entry[4:8]
                        date_str = f"{yyyy}-{mm}-{dd}"
                        datetime.strptime(date_str, '%Y-%m-%d')
                        dates.append(entry)
                except (ValueError, IndexError):
                    pass
    
    # Sort most recent first
    dates.sort(reverse=True, key=lambda x: (x[4:8], x[:2], x[2:4]))
    return dates


def find_files_for_date(date_folder):
    """Find all FITS files for a given date"""
    date_path = os.path.join(DATA_BASE_DIR, date_folder)
    if not os.path.exists(date_path):
        return []
    
    fits_files = glob.glob(os.path.join(date_path, "*.fits"))
    fits_files = [f for f in fits_files if os.path.getsize(f) > 0]  # Filter empty files
    fits_files.sort()  # Chronological order
    
    return [os.path.basename(f) for f in fits_files]


def load_s2p_file(filename):
    """
    Load S2P (Touchstone) file and extract S21 magnitude in dB
    Uses scikit-rf to properly handle rectangular (real/imaginary) format
    """
    try:
        import skrf as rf
        
        # Load the network from S2P file
        network = rf.Network(filename)
        
        # Get frequency in MHz
        freqs_mhz = network.frequency.f / 1e6
        
        # Extract S21 (parameter [1,0] in S-parameter matrix)
        # S21 is the forward transmission coefficient
        s21_complex = network.s[:, 1, 0]  # s[freq_index, port_out, port_in]
        
        # Convert complex S21 to magnitude in dB: 20*log10(|S21|)
        s21_mag = np.abs(s21_complex)
        s21_db = 20 * np.log10(s21_mag + 1e-12)  # Add small value to avoid log(0)
        
        return np.array(freqs_mhz), np.array(s21_db)
            
    except Exception as e:
        print(f"Error loading S2P file {filename}: {e}")
        import traceback
        traceback.print_exc()
        return None, None


def load_s21_corrections():
    """Load S21 correction data for all filters"""
    if not os.path.exists(S21_DIR):
        print(f"S21 directory not found: {S21_DIR}")
        return None
    
    s21_data = {}
    
    for filt_num in range(21):
        s2p_file = os.path.join(S21_DIR, f"filter_{filt_num:02d}.s2p")
        
        if not os.path.exists(s2p_file):
            continue
        
        freqs, s21_db = load_s2p_file(s2p_file)
        
        if freqs is not None:
            s21_data[filt_num] = {
                'freqs': freqs,
                's21_db': s21_db
            }
    
    if len(s21_data) > 0:
        print(f"Loaded S21 corrections for {len(s21_data)}/21 filters")
    
    return s21_data if len(s21_data) > 0 else None


def calculate_filter_normalization_factors(frequencies, powers, filters, freq_min=50, freq_max=80, excluded_filters=[0, 1, 13, 16, 20]):
    """
    Calculate normalization factors (dB offsets) for each filter to align measured spectra.
    
    Uses only data in a specified frequency region (freq_min to freq_max) to calculate offsets,
    then applies the same offset to the entire spectrum.
    
    Args:
        frequencies: list of all measured frequencies
        powers: list of all measured powers (in dBm)
        filters: list of filter indices for each measurement
        freq_min: minimum frequency (MHz) for alignment region
        freq_max: maximum frequency (MHz) for alignment region
        excluded_filters: filters to exclude from normalization
    
    Returns:
        dict with normalization offset (in dB) for each filter
    """
    if not APPLY_FILTER_NORMALIZATION:
        return None
    
    # Organize data by filter
    filter_data = {}
    for freq, power, filt in zip(frequencies, powers, filters):
        if filt not in filter_data:
            filter_data[filt] = {'freqs': [], 'powers': []}
        filter_data[filt]['freqs'].append(freq)
        filter_data[filt]['powers'].append(power)
    
    # Get valid filters (exclude specified ones)
    valid_filters = [f for f in filter_data.keys() if f not in excluded_filters and len(filter_data[f]['freqs']) > 1]
    
    if len(valid_filters) < 2:
        print("Not enough valid filters for normalization")
        return None
    
    # Extract data in alignment frequency region for each filter
    region_data = {}
    for filt in valid_filters:
        freqs = np.array(filter_data[filt]['freqs'])
        powers = np.array(filter_data[filt]['powers'])
        
        # Find indices in the frequency region
        mask = (freqs >= freq_min) & (freqs <= freq_max)
        region_powers = powers[mask]
        
        if len(region_powers) > 0:
            # Use mean power in this region for normalization
            region_data[filt] = np.mean(region_powers)
    
    if len(region_data) < 2:
        print(f"Not enough data in frequency region {freq_min}-{freq_max} MHz for normalization")
        return None
    
    # Calculate mean power in region across all filters
    mean_region_power = np.mean(list(region_data.values()))
    
    # Calculate per-filter offset
    normalization = {}
    for filt in region_data:
        # Offset = mean - individual (brings all filters to mean level in region)
        offset = mean_region_power - region_data[filt]
        normalization[filt] = offset
    
    print(f"Calculated normalization factors for {len(normalization)} filters (using {freq_min}-{freq_max} MHz region)")
    print(f"Mean power in region: {mean_region_power:.2f} dBm")
    print(f"Normalization offsets (dB): {{{', '.join(f'{f}: {o:.2f}' for f, o in sorted(normalization.items())[:5])}...}}")
    
    return normalization if len(normalization) > 0 else None


def get_per_filter_calibration(data_date=None):
    """
    Load per-filter calibration from FITS files.
    Tries to find calibration files closest to data_date if provided.
    
    Args:
        data_date: Date string in MMddyyyy format (e.g., '11062025')
    """
    try:
        cal_files = glob.glob(os.path.join(CALIB_DIR, "*.fits"))
        cal_files = [f for f in cal_files if os.path.getsize(f) > 0]
        
        if len(cal_files) < 2:
            print(f"Not enough calibration files found (need 2, found {len(cal_files)}))")
            return None
        
        # Sort by modification time, with preference for dates closest to data_date
        if data_date:
            try:
                data_dt = datetime.strptime(data_date, '%m%d%Y')
                cal_files.sort(key=lambda f: abs(os.path.getmtime(f) - data_dt.timestamp()))
                print(f"Using calibration files closest to data date: {data_date}")
            except ValueError:
                # Fall back to most recent if date parsing fails
                cal_files.sort(key=os.path.getmtime, reverse=True)
        else:
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
        # low_power_dbm = -40.0
        # high_power_dbm = -31.0
        # low_power_dbm = -23.0
        # high_power_dbm = -14.0
        low_power_dbm = -9.0
        high_power_dbm = 0.0
        
        s21_corrections = load_s21_corrections()
        filter_centers = [904.0 + i * 2.6 for i in range(21)]
        
        with fits.open(low_power_file) as hdul:
            low_data = hdul[1].data
        
        with fits.open(high_power_file) as hdul:
            high_data = hdul[1].data
        
        filter_calibrations = {}
        
        for filt_num in range(21):
            center_freq = filter_centers[filt_num]
            
            low_voltage = None
            high_voltage = None
            
            best_lo_low = None
            best_dist_low = float('inf')
            
            for row in low_data:
                lo_freq = int(float(row[5]))
                dist = abs(lo_freq - center_freq)
                if dist < best_dist_low:
                    best_dist_low = dist
                    best_lo_low = row
            
            if best_lo_low is not None and best_dist_low < 1.0:
                a1 = best_lo_low[0][:7]
                a2 = best_lo_low[1][:7]
                a3 = best_lo_low[2][:7]
                combined_ints = cal.makeSingleListOfInts(a1, a2, a3)
                volts = cal.toVolts(combined_ints)
                low_voltage = volts[filt_num]
            
            best_lo_high = None
            best_dist_high = float('inf')
            
            for row in high_data:
                lo_freq = int(float(row[5]))
                dist = abs(lo_freq - center_freq)
                if dist < best_dist_high:
                    best_dist_high = dist
                    best_lo_high = row
            
            if best_lo_high is not None and best_dist_high < 1.0:
                a1 = best_lo_high[0][:7]
                a2 = best_lo_high[1][:7]
                a3 = best_lo_high[2][:7]
                combined_ints = cal.makeSingleListOfInts(a1, a2, a3)
                volts = cal.toVolts(combined_ints)
                high_voltage = volts[filt_num]
            
            if low_voltage is None or high_voltage is None:
                continue
            
            s21_loss_db = 0.0
            
            if s21_corrections and filt_num in s21_corrections:
                s21_freqs = s21_corrections[filt_num]['freqs']
                s21_db = s21_corrections[filt_num]['s21_db']
                s21_loss_db = np.interp(center_freq, s21_freqs, s21_db)
            
            low_power_at_detector = low_power_dbm + s21_loss_db
            high_power_at_detector = high_power_dbm + s21_loss_db
            
            voltage_diff = high_voltage - low_voltage
            
            if abs(voltage_diff) < 0.001:
                continue
            
            slope = (high_power_at_detector - low_power_at_detector) / voltage_diff
            intercept = low_power_at_detector - slope * low_voltage
            
            filter_calibrations[filt_num] = {
                'slope': slope,
                'intercept': intercept,
                'low_v': low_voltage,
                'high_v': high_voltage,
                'center_freq': center_freq,
                's21_db': s21_loss_db
            }
        
        if len(filter_calibrations) < 21:
            print(f"Warning: Only calibrated {len(filter_calibrations)}/21 filters")
        
        return filter_calibrations if len(filter_calibrations) > 0 else None
        
    except Exception as e:
        print(f"Error loading per-filter calibration: {e}")
        return None


def load_calibration_data(data_date=None, data_time=None):
    """
    Load calibration FITS files for +5dBm and -4dBm, closest in time to the data
    data_date: MMddyyyy format (e.g., '11062025')
    data_time: HHMMSS format (e.g., '123456')
    Returns (lo_freq_pos, data21_pos, lo_freq_neg, data21_neg, pos_file, neg_file) or (None, None, None, None, None, None) if not found
    """
    if not FILTER_PLOTTING_AVAILABLE:
        return None, None, None, None, None, None
    
    def extract_time_from_filename(filepath):
        """Extract time from calibration filename (MMddyyyy_HHMMSS_±XdBm.fits)"""
        try:
            basename = os.path.basename(filepath)
            parts = basename.split('_')
            if len(parts) >= 2:
                time_str = parts[1]  # HHMMSS
                return int(time_str) if len(time_str) == 6 else None
        except:
            pass
        return None
    
    try:
        cal_files = glob.glob(os.path.join(CALIB_DIR, "*.fits"))
        cal_files = [f for f in cal_files if os.path.getsize(f) > 0]
        
        if len(cal_files) < 2:
            return None, None, None, None, None, None
        
        # If we have data_time, find calibration closest to that time
        if data_date and data_time:
            try:
                data_time_int = int(data_time)  # HHMMSS as integer
                
                # Find calibration files with matching +5dBm and -4dBm
                pos_files = []
                neg_files = []
                
                for f in cal_files:
                    basename = os.path.basename(f)
                    if "+5" in basename:
                        pos_files.append(f)
                    elif "-4" in basename:
                        neg_files.append(f)
                
                # Find closest time for each based on filename time
                pos_file = None
                if pos_files:
                    pos_file = min(pos_files, key=lambda f: abs(extract_time_from_filename(f) - data_time_int) if extract_time_from_filename(f) else float('inf'))
                
                neg_file = None
                if neg_files:
                    neg_file = min(neg_files, key=lambda f: abs(extract_time_from_filename(f) - data_time_int) if extract_time_from_filename(f) else float('inf'))
                
                if pos_file and neg_file:
                    lo_pos, data_pos = load_filterbank_table(pos_file)
                    lo_neg, data_neg = load_filterbank_table(neg_file)
                    print(f"Loaded calibrations: {os.path.basename(pos_file)} (pos), {os.path.basename(neg_file)} (neg)")
                    return lo_pos, data_pos, lo_neg, data_neg, pos_file, neg_file
            except (ValueError, TypeError):
                pass
        
        # Fall back to just finding any +5dBm and -4dBm files, sorted by recency
        cal_files.sort(key=os.path.getmtime, reverse=True)
        
        pos_file = None
        neg_file = None
        
        for f in cal_files:
            basename = os.path.basename(f)
            if "+5" in basename and pos_file is None:
                pos_file = f
            elif "-4" in basename and neg_file is None:
                neg_file = f
        
        if pos_file is None or neg_file is None:
            return None, None, None, None, None, None
        
        lo_pos, data_pos = load_filterbank_table(pos_file)
        lo_neg, data_neg = load_filterbank_table(neg_file)
        
        print(f"Loaded calibrations: {os.path.basename(pos_file)} (pos), {os.path.basename(neg_file)} (neg)")
        return lo_pos, data_pos, lo_neg, data_neg, pos_file, neg_file
        
    except Exception as e:
        print(f"Error loading calibration data: {e}")
        return None, None, None, None


def process_spectrum_data(filepath, filter_cal):
    """Process FITS file and return spectrum data and calculated normalization factors"""
    try:
        hdul = fits.open(filepath)
        data = hdul[1].data
        sys_voltage = hdul[1].header.get('SYSVOLT', 0.0)
        hdul.close()
        
        if len(data) == 0:
            return None, None, None, None, None, None
        
        first_state = data[0][4]
        
        all_frequencies = []
        all_voltages = []
        all_powers = []
        all_filters = []
        
        for sweep_idx in range(len(data)):
            a1 = data[sweep_idx][0][:7]
            a2 = data[sweep_idx][1][:7]
            a3 = data[sweep_idx][2][:7]
            lo_freq = int(float(data[sweep_idx][5]))
            
            if cal:
                combined_ints = cal.makeSingleListOfInts(a1, a2, a3)
                volts_data = cal.toVolts(combined_ints)
            else:
                # Fallback: simple conversion if cal not available
                volts_data = [0.0] * 21
            
            db_data = []
            for filt_num, voltage in enumerate(volts_data):
                if filter_cal and filt_num in filter_cal:
                    slope = filter_cal[filt_num]['slope']
                    intercept = filter_cal[filt_num]['intercept']
                    power = slope * voltage + intercept
                else:
                    power = -43.5 * voltage + 24.98
                
                db_data.append(power)
            
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
            'filename': os.path.basename(filepath),
            'timestamp': datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Calculate normalization factors from this measurement if enabled
        normalization = calculate_filter_normalization_factors(all_frequencies, all_powers, all_filters)
        
        return all_frequencies, all_voltages, all_powers, all_filters, metadata, normalization
        
    except Exception as e:
        print(f"Error processing file {filepath}: {e}")
        return None, None, None, None, None, None


@app.callback(
    Output('available-dates', 'data'),
    Input('date-dropdown', 'id')  # Trigger on load
)
def populate_dates(_):
    """Populate available dates on app load"""
    dates = find_available_dates()
    return dates


@app.callback(
    Output('date-dropdown', 'options'),
    Input('available-dates', 'data')
)
def update_date_options(dates):
    """Update date dropdown options"""
    if not dates:
        return []
    return [{'label': d, 'value': d} for d in dates]


@app.callback(
    Output('file-dropdown', 'options'),
    Input('date-dropdown', 'value')
)
def update_file_options(selected_date):
    """Update file dropdown based on selected date"""
    if not selected_date:
        return []
    
    files = find_files_for_date(selected_date)
    return [{'label': f, 'value': f} for f in files]


@app.callback(
    [Output('voltage-plot', 'figure'),
     Output('power-plot', 'figure'),
     Output('calib-positive-plot', 'figure'),
     Output('calib-negative-plot', 'figure'),
     Output('status-info', 'children')],
    [Input('load-button', 'n_clicks')],
    [State('date-dropdown', 'value'),
     State('file-dropdown', 'value')]
)
def load_and_display(n_clicks, selected_date, selected_file):
    """Load and display selected file and calibration data"""
    
    if not selected_date or not selected_file or n_clicks == 0:
        # Initial state - no file loaded
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title="Select a date and file, then click Load",
            xaxis_title="Frequency (MHz)",
            yaxis_title="Value",
            template="plotly_white"
        )
        return empty_fig, empty_fig, empty_fig, empty_fig, "Ready to load data"
    
    # Extract time from data filename (format: "MMddyyyy_HHMMSS.fits")
    data_time_display = ""
    if selected_file:
        file_parts = selected_file.split('_')
        if len(file_parts) >= 2:
            time_part = file_parts[1].replace('.fits', '')
            if len(time_part) == 6:  # HHMMSS
                data_time_display = f"{time_part[0:2]}:{time_part[2:4]}:{time_part[4:6]}"
    
    # Construct full filepath
    filepath = os.path.join(DATA_BASE_DIR, selected_date, selected_file)
    
    if not os.path.exists(filepath):
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title="File not found",
            template="plotly_white"
        )
        return empty_fig, empty_fig, empty_fig, empty_fig, f"Error: File not found at {filepath}"
    
    # Load calibration (pass selected_date for proper calibration file matching)
    filter_cal = get_per_filter_calibration(data_date=selected_date)
    
    # Process data
    result = process_spectrum_data(filepath, filter_cal)
    
    if result[0] is None:
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title="Error reading data",
            template="plotly_white"
        )
        return empty_fig, empty_fig, empty_fig, empty_fig, "Error processing data file"
    
    frequencies, voltages, powers, filters, metadata, normalization = result
    
    # Apply normalization if calculated
    if normalization:
        normalized_powers = []
        for power, filt in zip(powers, filters):
            if filt in normalization:
                normalized_powers.append(power + normalization[filt])
            else:
                normalized_powers.append(power)
        powers = normalized_powers
    
    # Create color palette
    from plotly.colors import qualitative
    colors = (qualitative.Dark24[:21] if len(qualitative.Dark24) >= 21 
              else qualitative.Dark24 + qualitative.Light24[:21-len(qualitative.Dark24)])
    
    # Organize data by filter
    filter_data = {}
    for freq, volt, power, filt in zip(frequencies, voltages, powers, filters):
        if filt not in filter_data:
            filter_data[filt] = {'freq': [], 'volt': [], 'power': []}
        filter_data[filt]['freq'].append(freq)
        filter_data[filt]['volt'].append(volt)
        filter_data[filt]['power'].append(power)
    
    # Create voltage plot
    voltage_fig = go.Figure()
    for filt_num in [i for i in range(21) if i not in [0, 1, 13, 16, 20]]:  # Exclude 0, 1, 13, 16, 20
        if filt_num in filter_data:
            voltage_fig.add_trace(go.Scatter(
                x=filter_data[filt_num]['freq'],
                y=filter_data[filt_num]['volt'],
                mode='markers',
                marker=dict(size=3, color=colors[filt_num]),
                name=f'Filter {filt_num}',
                showlegend=False,
                hovertemplate=f'<b>Filter {filt_num}</b><br>' +
                              '<b>Freq</b>: %{x:.1f} MHz<br>' +
                              '<b>Voltage</b>: %{y:.4f} V<br>' +
                              '<extra></extra>'
            ))
    
    voltage_fig.update_layout(
        title=f"Raw Detector Voltages - {data_time_display}",
        xaxis_title="Frequency (MHz)",
        yaxis_title="Voltage (V)",
        xaxis_range=[0, 350],
        yaxis_range=[0.8, 2.2],
        template="plotly_white",
        hovermode='closest',
        showlegend=False,
        height=480,
        margin=dict(b=60)
    )
    
    # Create power plot
    power_fig = go.Figure()
    for filt_num in [i for i in range(21) if i not in [0, 1, 13, 16, 20]]:  # Exclude 0, 1, 13, 16, 20
        if filt_num in filter_data:
            power_fig.add_trace(go.Scatter(
                x=filter_data[filt_num]['freq'],
                y=filter_data[filt_num]['power'],
                mode='markers',
                marker=dict(size=3, color=colors[filt_num]),
                name=f'Filter {filt_num}',
                showlegend=False,
                hovertemplate=f'<b>Filter {filt_num}</b><br>' +
                              '<b>Freq</b>: %{x:.1f} MHz<br>' +
                              '<b>Power</b>: %{y:.2f} dBm<br>' +
                              '<extra></extra>'
            ))
    
    power_fig.update_layout(
        title=f"Calibrated Power Spectrum - {data_time_display}",
        xaxis_title="Frequency (MHz)",
        yaxis_title="Power (dBm)",
        yaxis_range=[-70,-20],
        xaxis_range=[0, 300],
        template="plotly_white",
        hovermode='closest',
        showlegend=False,
        height=480,
        margin=dict(b=60)
    )
    
    # Load and create calibration plots
    calib_pos_fig = go.Figure()
    calib_neg_fig = go.Figure()
    
    if FILTER_PLOTTING_AVAILABLE:
        try:
            # Extract time from data filename (format: "MMddyyyy_HHMMSS.fits")
            data_time = None
            if selected_file:
                file_parts = selected_file.split('_')
                if len(file_parts) >= 2:
                    time_part = file_parts[1].replace('.fits', '')
                    if len(time_part) == 6:  # HHMMSS
                        data_time = time_part
            
            lo_pos, data_pos, lo_neg, data_neg, pos_file, neg_file = load_calibration_data(data_date=selected_date, data_time=data_time)
            
            # Get timestamps for the calibration files from filename
            pos_timestamp = ""
            neg_timestamp = ""
            if pos_file:
                basename = os.path.basename(pos_file)
                parts = basename.split('_')
                if len(parts) >= 2:
                    time_str = parts[1]  # HHMMSS
                    pos_time = f"{time_str[0:2]}:{time_str[2:4]}:{time_str[4:6]}"
                    pos_timestamp = f" ({pos_time})"
            if neg_file:
                basename = os.path.basename(neg_file)
                parts = basename.split('_')
                if len(parts) >= 2:
                    time_str = parts[1]  # HHMMSS
                    neg_time = f"{time_str[0:2]}:{time_str[2:4]}:{time_str[4:6]}"
                    neg_timestamp = f" ({neg_time})"
            
            if data_pos is not None and len(lo_pos) > 0:
                # Convert to voltage for positive calibration
                volts_pos = adc_counts_to_voltage(data_pos, ref=5.0, mode="c_like")
                
                calib_pos_fig = go.Figure()
                for filt_idx in range(21):
                    calib_pos_fig.add_trace(go.Scatter(
                        x=lo_pos,
                        y=volts_pos[:, filt_idx],
                        mode='lines+markers',
                        name=f'Filter {filt_idx}',
                        showlegend=False,
                        line=dict(width=1.5),
                        marker=dict(size=4),
                        hovertemplate='<b>Filter ' + str(filt_idx) + '</b><br>' +
                                      'LO: %{x:.1f} MHz<br>' +
                                      'Voltage: %{y:.4f} V<br>' +
                                      '<extra></extra>'
                    ))
                
                calib_pos_fig.update_layout(
                    title=f"+5 dBm Calibration - Filter Responses (Voltage) - {selected_date}{pos_timestamp}",
                    xaxis_title="LO Frequency (MHz)",
                    yaxis_title="Voltage (V)",
                    xaxis_range=[900, 960],
                    yaxis_range=[0.8, 2.2],
                    template="plotly_white",
                    hovermode='closest',
                    showlegend=False,
                    height=480,
                    margin=dict(b=60)
                )
            
            if data_neg is not None and len(lo_neg) > 0:
                # Convert to voltage for negative calibration
                volts_neg = adc_counts_to_voltage(data_neg, ref=5.0, mode="c_like")
                
                calib_neg_fig = go.Figure()
                for filt_idx in range(21):
                    calib_neg_fig.add_trace(go.Scatter(
                        x=lo_neg,
                        y=volts_neg[:, filt_idx],
                        mode='lines+markers',
                        name=f'Filter {filt_idx}',
                        showlegend=False,
                        line=dict(width=1.5),
                        marker=dict(size=4),
                        hovertemplate='<b>Filter ' + str(filt_idx) + '</b><br>' +
                                      'LO: %{x:.1f} MHz<br>' +
                                      'Voltage: %{y:.4f} V<br>' +
                                      '<extra></extra>'
                    ))
                
                calib_neg_fig.update_layout(
                    title=f"-4 dBm Calibration - Filter Responses (Voltage) - {selected_date}{neg_timestamp}",
                    xaxis_title="LO Frequency (MHz)",
                    yaxis_title="Voltage (V)",
                    xaxis_range=[900, 960],
                    yaxis_range=[0.8, 2.2],
                    template="plotly_white",
                    hovermode='closest',
                    showlegend=False,
                    height=480,
                    margin=dict(b=60)
                )
        except Exception as e:
            print(f"Error creating calibration plots: {e}")
            import traceback
            traceback.print_exc()
    
    # Status
    if filter_cal:
        num_calibrated = len(filter_cal)
        num_with_s21 = sum(1 for f in filter_cal.values() if f.get('s21_db', 0) != 0)
        
        if num_with_s21 > 0:
            cal_status = f"✓ Per-filter cal ({num_calibrated}/21) + S21 ({num_with_s21}/21)"
        else:
            cal_status = f"✓ Per-filter calibration ({num_calibrated}/21)"
    else:
        cal_status = "⚠ No calibration (using fallback)"
    
    status_text = (f"File: {metadata['filename']} | "
                   f"Voltage: {metadata['voltage']:.2f} V | "
                   f"State: {metadata['state']} | "
                   f"Sweeps: {metadata['num_sweeps']} | "
                   f"{cal_status}")
    
    return voltage_fig, power_fig, calib_pos_fig, calib_neg_fig, status_text


if __name__ == '__main__':
    print("\n" + "="*60)
    print("High-Z Filterbank Historical Viewer")
    print("="*60)
    print(f"\nData directory: {DATA_BASE_DIR}")
    print(f"Calibration directory: {CALIB_DIR}")
    print("\nStarting server...")
    print("\nAccess the dashboard at:")
    print("  http://localhost:8050")
    print("\nPress Ctrl+C to stop")
    print("="*60 + "\n")
    
    app.run(debug=False, host='127.0.0.1', port=8050)
