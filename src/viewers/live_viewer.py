#!/usr/bin/env python3
"""
High-Z Filterbank Live Viewer

Real-time viewer for ongoing filterbank data acquisition using Plotly Dash.
Automatically displays the most recent spectrum as data is being collected.
"""

import os
import glob
import argparse
import time
from pathlib import Path
from datetime import datetime
import numpy as np
from dash import Dash, dcc, html, Input, Output
import plotly.graph_objs as go
import traceback

# Import utilities
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utilities import io_utils, plot_utils

# Configuration defaults
DEFAULT_DATA_DIR = "/media/peterson/INDURANCE/Data"
DEFAULT_S21_DIR = "/home/peterson/highz/highz-filterbank/characterization/s_parameters"
DEFAULT_REFRESH_INTERVAL = 3000  # milliseconds (3 seconds)

# Calibration alignment defaults
DEFAULT_ALIGN_FREQ_MIN = 50  # MHz
DEFAULT_ALIGN_FREQ_MAX = 80  # MHz

# Initialize Dash app
app = Dash(__name__)
app.title = "High-Z Filterbank Live Viewer"

# Layout
app.layout = html.Div([
    # Header
    html.Div([
        html.H1("High-Z Filterbank Live Viewer", 
                style={'textAlign': 'center', 'color': '#2c3e50', 'marginBottom': '10px'}),
        html.Div([
            html.Span(id='status-info', style={'fontSize': '14px', 'color': '#27ae60', 'marginRight': '20px'}),
            html.Span(id='last-update', style={'fontSize': '12px', 'color': '#7f8c8d'}),
        ], style={'textAlign': 'center'}),
    ], style={'marginBottom': '15px'}),
    
    # Settings panel
    html.Details([
        html.Summary("⚙️ Settings", style={'fontWeight': 'bold', 'cursor': 'pointer'}),
        html.Div([
            # View mode
            html.Div([
                html.Label("View Mode:", style={'fontWeight': 'bold', 'marginRight': '10px'}),
                dcc.RadioItems(
                    id='view-mode',
                    options=[
                        {'label': ' Power Only', 'value': 'power'},
                        {'label': ' Diagnostics Grid', 'value': 'grid'}
                    ],
                    value='power',
                    inline=True,
                    style={'display': 'inline-block'}
                ),
            ], style={'marginBottom': '10px'}),
            
            # Filtercal visualization
            html.Div([
                html.Label("Filtercal View:", style={'fontWeight': 'bold', 'marginRight': '10px'}),
                dcc.RadioItems(
                    id='filtercal-mode',
                    options=[
                        {'label': ' Line Plots', 'value': 'lines'},
                        {'label': ' Heatmap', 'value': 'heatmap'}
                    ],
                    value='lines',
                    inline=True,
                    style={'display': 'inline-block'}
                ),
            ], style={'marginBottom': '10px'}),
            
            # Calibration toggles
            html.Div([
                html.Label("Calibration:", style={'fontWeight': 'bold', 'marginRight': '10px'}),
                dcc.Checklist(
                    id='calibration-toggles',
                    options=[
                        {'label': ' Apply S21 Corrections', 'value': 's21'},
                        {'label': ' Apply Filter Alignment', 'value': 'alignment'}
                    ],
                    value=['s21', 'alignment'],
                    inline=True
                ),
            ], style={'marginBottom': '10px'}),
            
            # Filter exclusions
            html.Div([
                html.Label("Exclude Filters:", style={'fontWeight': 'bold', 'marginRight': '10px'}),
                dcc.Input(
                    id='filter-exclusions',
                    type='text',
                    placeholder='e.g., 0,1,13,16,20',
                    style={'width': '200px'}
                ),
                html.Span(" (comma-separated)", style={'fontSize': '12px', 'color': '#7f8c8d'}),
            ], style={'marginBottom': '10px'}),
            
            # Refresh interval
            html.Div([
                html.Label("Refresh Interval:", style={'fontWeight': 'bold', 'marginRight': '10px'}),
                dcc.Input(
                    id='refresh-interval-input',
                    type='number',
                    value=DEFAULT_REFRESH_INTERVAL / 1000,
                    min=0.5,
                    max=10,
                    step=0.5,
                    style={'width': '80px', 'marginRight': '5px'}
                ),
                html.Span(" seconds", style={'fontSize': '12px', 'color': '#7f8c8d'}),
            ]),
        ], style={'padding': '10px'})
    ], style={'marginBottom': '15px', 'backgroundColor': '#ecf0f1', 
              'borderRadius': '4px', 'padding': '10px'}),
    
    # Plot containers
    html.Div(id='plot-container'),
    
    # Auto-refresh interval
    dcc.Interval(
        id='refresh-interval',
        interval=DEFAULT_REFRESH_INTERVAL,  # milliseconds
        n_intervals=0
    ),
    
    # Data stores
    dcc.Store(id='data-dir-store', data=DEFAULT_DATA_DIR),
    dcc.Store(id='s21-dir-store', data=DEFAULT_S21_DIR),
    dcc.Store(id='align-freq-min-store', data=DEFAULT_ALIGN_FREQ_MIN),
    dcc.Store(id='align-freq-max-store', data=DEFAULT_ALIGN_FREQ_MAX),
])


def find_most_recent_cycle(data_dir):
    """Find the most recently modified cycle directory with valid data"""
    from astropy.io import fits
    
    date_dirs = []
    if os.path.exists(data_dir):
        for entry in os.listdir(data_dir):
            path = os.path.join(data_dir, entry)
            if os.path.isdir(path) and len(entry) == 8 and entry.isdigit():
                date_dirs.append(path)
    
    if not date_dirs:
        return None
    
    # Find all cycle directories across all dates
    all_cycles = []
    for date_dir in date_dirs:
        for entry in os.listdir(date_dir):
            cycle_path = os.path.join(date_dir, entry)
            if os.path.isdir(cycle_path) and entry.startswith("Cycle_"):
                all_cycles.append(cycle_path)
    
    if not all_cycles:
        return None
    
    # Sort by modification time (most recent first)
    all_cycles.sort(key=os.path.getmtime, reverse=True)
    
    # Return first cycle that has at least one state file with data
    for cycle in all_cycles:
        state_files = glob.glob(os.path.join(cycle, "state_*.fits"))
        for f in state_files:
            try:
                with fits.open(f) as hdul:
                    if hdul[1].data is not None and len(hdul[1].data) > 0:
                        return cycle  # Found a cycle with valid data
            except Exception:
                continue
    
    # If no cycles with data found, return None
    return None


def find_latest_spectrum(cycle_dir):
    """
    Find the most recent spectrum in the most recent state file.
    Returns (state_file_path, spectrum_index, total_spectra)
    """
    from astropy.io import fits
    
    state_files = glob.glob(os.path.join(cycle_dir, "state_*.fits"))
    
    # Filter out files with no actual data (empty FITS tables)
    valid_files = []
    for f in state_files:
        try:
            with fits.open(f) as hdul:
                if hdul[1].data is not None and len(hdul[1].data) > 0:
                    valid_files.append(f)
        except Exception:
            continue
    
    if not valid_files:
        return None, 0, 0
    
    # Get most recently modified state file with data
    latest_state = max(valid_files, key=os.path.getmtime)
    
    # Check how many spectra are in it
    try:
        with fits.open(latest_state) as hdul:
            n_spectra = hdul[0].header.get('N_SPECTRA', len(hdul[1].data))
        
        # Return path to most recent spectrum (last one in file)
        return latest_state, n_spectra - 1, n_spectra
    except Exception as e:
        print(f"Error reading state file {latest_state}: {e}")
        return None, 0, 0


def load_calibration_data(cycle_dir, s21_dir, apply_s21):
    """Load filtercal and build calibration"""
    # Find filtercal files
    filtercal_files = {'pos': None, 'neg': None}
    
    for f in glob.glob(os.path.join(cycle_dir, "filtercal_*.fits")):
        if os.path.getsize(f) == 0:
            continue
        basename = os.path.basename(f)
        if "+5" in basename or "pos" in basename.lower():
            filtercal_files['pos'] = f
        elif "-4" in basename or "neg" in basename.lower():
            filtercal_files['neg'] = f
    
    if not filtercal_files['pos'] or not filtercal_files['neg']:
        return None
    
    try:
        filtercal_pos = io_utils.load_filtercal(filtercal_files['pos'])
        filtercal_neg = io_utils.load_filtercal(filtercal_files['neg'])
        
        # Load S21 corrections if enabled
        s21_data = None
        if apply_s21:
            s21_data = io_utils.load_s21_corrections(s21_dir)
        
        # Build calibration
        filter_cal = io_utils.build_filter_calibration(
            filtercal_pos, filtercal_neg,
            s21_data=s21_data
        )
        
        return {
            'pos': filtercal_pos,
            'neg': filtercal_neg,
            'calibration': filter_cal
        }
    except Exception as e:
        print(f"Error loading calibration: {e}")
        return None


@app.callback(
    Output('refresh-interval', 'interval'),
    Input('refresh-interval-input', 'value')
)
def update_refresh_interval(interval_seconds):
    """Update auto-refresh interval"""
    if interval_seconds and interval_seconds > 0:
        return int(interval_seconds * 1000)
    return DEFAULT_REFRESH_INTERVAL


@app.callback(
    [Output('plot-container', 'children'),
     Output('status-info', 'children'),
     Output('last-update', 'children')],
    [Input('refresh-interval', 'n_intervals'),
     Input('view-mode', 'value'),
     Input('filtercal-mode', 'value'),
     Input('calibration-toggles', 'value'),
     Input('filter-exclusions', 'value'),
     Input('data-dir-store', 'data'),
     Input('s21-dir-store', 'data'),
     Input('align-freq-min-store', 'data'),
     Input('align-freq-max-store', 'data')]
)
def update_live_view(n_intervals, view_mode, filtercal_mode, calib_toggles,
                     filter_exclusions_str, data_dir, s21_dir,
                     align_freq_min, align_freq_max):
    """Auto-refresh and update plots with latest data"""
    
    # Debug logging
    print(f"\n=== UPDATE CALLED (interval {n_intervals}) ===")
    print(f"View mode: {view_mode}")
    print(f"Data dir: {data_dir}")
    
    # Find most recent cycle
    cycle_dir = find_most_recent_cycle(data_dir)
    print(f"Found cycle: {cycle_dir}")
    
    if not cycle_dir:
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title="No data found - waiting for acquisition to start...",
            template="plotly_white",
            height=400
        )
        status = "⚠️ No data available"
        last_update = f"Last checked: {datetime.now().strftime('%H:%M:%S')}"
        return html.Div([dcc.Graph(figure=empty_fig)]), status, last_update
    
    # Find latest spectrum
    state_file, spectrum_idx, n_spectra = find_latest_spectrum(cycle_dir)
    
    if not state_file:
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title=f"Waiting for data in {os.path.basename(cycle_dir)}...",
            template="plotly_white",
            height=400
        )
        status = f"📁 {os.path.basename(cycle_dir)}"
        last_update = f"Last checked: {datetime.now().strftime('%H:%M:%S')}"
        return html.Div([dcc.Graph(figure=empty_fig)]), status, last_update
    
    try:
        # Load spectrum
        spectrum_data = io_utils.load_state_file(state_file, spectrum_index=spectrum_idx)
        
        # Load calibration
        apply_s21 = 's21' in calib_toggles
        filtercal_data = load_calibration_data(cycle_dir, s21_dir, apply_s21)
        filter_cal = filtercal_data.get('calibration') if filtercal_data else None
        
        # Parse filter exclusions
        excluded_filters = []
        if filter_exclusions_str:
            try:
                excluded_filters = [int(x.strip()) for x in filter_exclusions_str.split(',') if x.strip()]
            except ValueError:
                pass
        
        # Apply calibration to spectrum
        result = io_utils.apply_calibration_to_spectrum(
            spectrum_data['data'],
            spectrum_data['lo_frequencies'],
            filter_cal if filter_cal else {},
            return_voltages=True
        )
        frequencies, powers, filter_indices, voltages = result
        
        # Apply filter alignment if enabled
        if 'alignment' in calib_toggles and filter_cal:
            normalization = io_utils.calculate_filter_normalization(
                frequencies, powers, filter_indices,
                freq_min=align_freq_min,
                freq_max=align_freq_max,
                excluded_filters=excluded_filters
            )
            if normalization:
                powers_normalized = []
                for power, filt in zip(powers, filter_indices):
                    if filt in normalization:
                        powers_normalized.append(power + normalization[filt])
                    else:
                        powers_normalized.append(power)
                powers = np.array(powers_normalized)
        
        # Extract timestamp
        timestamp = spectrum_data.get('timestamp', '')
        if isinstance(timestamp, str) and len(timestamp) >= 14:
            time_display = f"{timestamp[8:10]}:{timestamp[10:12]}:{timestamp[12:14]}"
        else:
            time_display = str(timestamp)
        
        # Create plots based on view mode
        if view_mode == 'power':
            # Power only - single large plot
            power_fig = plot_utils.create_power_plot(
                frequencies, powers, filter_indices,
                excluded_filters=excluded_filters,
                title_suffix=time_display
            )
            power_fig.update_layout(height=700)
            plot_content = html.Div([
                dcc.Graph(figure=power_fig, style={'height': '700px'})
            ])
        
        else:  # grid mode
            # Create voltage and power plots
            voltage_fig = plot_utils.create_voltage_plot(
                frequencies, voltages, filter_indices,
                excluded_filters=excluded_filters,
                title_suffix=time_display
            )
            
            power_fig = plot_utils.create_power_plot(
                frequencies, powers, filter_indices,
                excluded_filters=excluded_filters,
                title_suffix=time_display
            )
            
            # Create filtercal plots if available
            if filtercal_data:
                filtercal_pos = filtercal_data['pos']
                filtercal_neg = filtercal_data['neg']
                
                time_pos = filtercal_pos.get('timestamp', '')
                time_neg = filtercal_neg.get('timestamp', '')
                
                if filtercal_mode == 'heatmap':
                    fig_pos, fig_neg = plot_utils.create_filtercal_heatmaps(
                        filtercal_pos, filtercal_neg,
                        time_pos=time_pos, time_neg=time_neg
                    )
                else:  # lines
                    fig_pos, fig_neg = plot_utils.create_filtercal_line_plots(
                        filtercal_pos, filtercal_neg,
                        time_pos=time_pos, time_neg=time_neg
                    )
            else:
                fig_pos = go.Figure()
                fig_pos.update_layout(title="No +5dBm filtercal", template="plotly_white")
                fig_neg = go.Figure()
                fig_neg.update_layout(title="No -4dBm filtercal", template="plotly_white")
            
            # 2x2 grid layout
            plot_content = html.Div([
                html.Div([
                    html.Div([
                        dcc.Graph(figure=voltage_fig, style={'height': '100%'})
                    ], style={'display': 'inline-block', 'width': '48%', 'marginRight': '2%', 
                             'verticalAlign': 'top'}),
                    
                    html.Div([
                        dcc.Graph(figure=power_fig, style={'height': '100%'})
                    ], style={'display': 'inline-block', 'width': '48%', 'verticalAlign': 'top'}),
                ], style={'marginBottom': '20px', 'height': '500px'}),
                
                html.Div([
                    html.Div([
                        dcc.Graph(figure=fig_pos, style={'height': '100%'})
                    ], style={'display': 'inline-block', 'width': '48%', 'marginRight': '2%', 
                             'verticalAlign': 'top'}),
                    
                    html.Div([
                        dcc.Graph(figure=fig_neg, style={'height': '100%'})
                    ], style={'display': 'inline-block', 'width': '48%', 'verticalAlign': 'top'}),
                ], style={'marginBottom': '20px', 'height': '500px'}),
            ])
        
        # Status and update time
        cycle_name = os.path.basename(cycle_dir)
        state_name = os.path.basename(state_file).replace('.fits', '')
        cal_status = "✓ Cal" if filtercal_data else "⚠️ No cal"
        status = f"🟢 Live | {cycle_name} | {state_name} | Spectrum {spectrum_idx+1}/{n_spectra} | {cal_status}"
        last_update = f"Updated: {datetime.now().strftime('%H:%M:%S')}"
        
        return plot_content, status, last_update
        
    except Exception as e:
        print(f"ERROR in callback: {e}")
        print(traceback.format_exc())
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title=f"Error loading data: {str(e)}",
            template="plotly_white",
            height=400
        )
        status = f"❌ Error: {str(e)[:50]}"
        last_update = f"Last checked: {datetime.now().strftime('%H:%M:%S')}"
        return html.Div([dcc.Graph(figure=empty_fig)]), status, last_update


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='High-Z Filterbank Live Viewer')
    parser.add_argument('--data-dir', default=DEFAULT_DATA_DIR,
                       help=f'Data directory (default: {DEFAULT_DATA_DIR})')
    parser.add_argument('--s21-dir', default=DEFAULT_S21_DIR,
                       help=f'S21 corrections directory (default: {DEFAULT_S21_DIR})')
    parser.add_argument('--port', type=int, default=8051,
                       help='Port to run server on (default: 8051)')
    parser.add_argument('--refresh', type=float, default=DEFAULT_REFRESH_INTERVAL/1000,
                       help=f'Refresh interval in seconds (default: {DEFAULT_REFRESH_INTERVAL/1000})')
    
    args = parser.parse_args()
    
    # Update default refresh interval
    DEFAULT_REFRESH_INTERVAL = int(args.refresh * 1000)
    
    print("\n" + "="*60)
    print("High-Z Filterbank Live Viewer")
    print("="*60)
    print(f"\nData directory: {args.data_dir}")
    print(f"S21 directory: {args.s21_dir}")
    print(f"Refresh interval: {args.refresh} seconds")
    print("\nStarting server...")
    print(f"\nAccess the live view at:")
    print(f"  http://localhost:{args.port}")
    print("\nPress Ctrl+C to stop")
    print("="*60 + "\n")
    
    app.run(debug=False, host='127.0.0.1', port=args.port)
