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
import json
import gc
import psutil
from pathlib import Path
from datetime import datetime
import numpy as np
from dash import Dash, dcc, html, Input, Output
import plotly.graph_objs as go
import traceback

# Import utilities
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utilities import plot_utils
from utilities.io_utils.fits_loader import load_prepared_spectrum_data
from utilities.io_utils.paths import get_default_s21_dir

# Configuration defaults
DEFAULT_DATA_DIR = "/media/peterson/INDURANCE/Data"
DEFAULT_S21_DIR = get_default_s21_dir()
DEFAULT_REFRESH_INTERVAL = 3000  # milliseconds (3 seconds)

# Calibration alignment defaults
DEFAULT_ALIGN_FREQ_MIN = 50  # MHz
DEFAULT_ALIGN_FREQ_MAX = 80  # MHz

# Calibration cache to avoid rebuilding on every refresh
_calibration_cache = {}
_last_cycle_dir = None

# Filtercal figure JSON cache (filtercal data is static per cycle)
_filtercal_json_cache = {}

# Initialize Dash app
app = Dash(__name__)
app.title = "High-Z Filterbank Live Viewer"

# Add Flask request timing
@app.server.before_request
def before_request():
    from flask import g
    g.request_start_time = time.time()

@app.server.after_request
def after_request(response):
    from flask import g, request
    if hasattr(g, 'request_start_time'):
        elapsed = (time.time() - g.request_start_time) * 1000
        if '_dash-update-component' in request.path:
            print(f"[FLASK] Full request time: {elapsed:.1f}ms")
    return response

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
    
    callback_start = time.time()  # Track full callback time
    
    # Track memory usage
    process = psutil.Process()
    mem_start = process.memory_info().rss / 1024 / 1024  # MB
    
    # Debug logging
    print(f"\n=== UPDATE CALLED (interval {n_intervals}) ===")
    print(f"View mode: {view_mode}")
    print(f"Data dir: {data_dir}")
    print(f"Memory at start: {mem_start:.1f} MB")
    
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
        print(f"\n*** CALLBACK TOTAL: {(time.time() - callback_start) * 1000:.1f}ms (no data) ***\n")
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
        print(f"\n*** CALLBACK TOTAL: {(time.time() - callback_start) * 1000:.1f}ms (no spectrum) ***\n")
        return html.Div([dcc.Graph(figure=empty_fig)]), status, last_update
    
    try:
        prepared = load_prepared_spectrum_data(
            state_file=state_file,
            spectrum_idx=spectrum_idx,
            cycle_dir=cycle_dir,
            s21_dir=s21_dir,
            calib_toggles=calib_toggles,
            filter_exclusions_str=filter_exclusions_str,
            align_freq_min=align_freq_min,
            align_freq_max=align_freq_max,
        )

        frequencies = prepared['frequencies']
        powers = prepared['powers']
        filter_indices = prepared['filter_indices']
        voltages = prepared['voltages']
        excluded_filters = prepared['excluded_filters']
        filtercal_data = prepared['filtercal_data']
        time_display = prepared['time_display']
        t0 = prepared['t0']
        t4 = prepared['t4']
        
        # Create plots based on view mode
        if view_mode == 'power':
            # Power only - single large plot
            power_fig = plot_utils.create_power_plot(
                frequencies, powers, filter_indices,
                excluded_filters=excluded_filters,
                title_suffix=time_display
            )
            power_fig.update_layout(height=700)
            
            # Plotly config for faster rendering
            plot_config = {
                'displayModeBar': False,
                'staticPlot': False,
                'responsive': True
            }
            
            # Use STATIC ID - allows Dash to update in-place instead of recreating
            plot_content = html.Div([
                dcc.Graph(id='main-power-graph', figure=power_fig, 
                         style={'height': '700px'}, config=plot_config)
            ])
            t5 = time.time()
            
            # Measure figure size
            fig_json = power_fig.to_json()
            fig_size_kb = len(fig_json) / 1024
            
            print(f"  Create plots: {(t5-t4)*1000:.1f}ms")
            print(f"  Power figure size: {fig_size_kb:.1f}KB")
            print(f"  TOTAL: {(t5-t0)*1000:.1f}ms")
        
        else:  # grid mode - 2x2 diagnostic grid with fast rendering
            # AGGRESSIVE OPTIMIZATION: Downsample data to reduce JSON payload
            # Grid mode is for diagnostics - full resolution not needed
            downsample_step = 2  # Show every 2nd point (reduces JSON by 50%)
            
            freq_sub = frequencies[::downsample_step]
            volt_sub = voltages[::downsample_step]
            power_sub = powers[::downsample_step]
            filt_sub = filter_indices[::downsample_step]
            
            print(f"  Grid downsampling: {len(frequencies)} -> {len(freq_sub)} points")
            
            # Create voltage spectrum plot (fast mode = no hover)
            voltage_fig = plot_utils.create_voltage_plot(
                freq_sub, volt_sub, filt_sub,
                excluded_filters=excluded_filters,
                title_suffix=time_display,
                fast_mode=True  # Disable hover for speed
            )
            
            # Create power spectrum plot (fast mode = no hover)
            power_fig = plot_utils.create_power_plot(
                freq_sub, power_sub, filt_sub,
                excluded_filters=excluded_filters,
                title_suffix=time_display,
                fast_mode=True  # Disable hover for speed
            )
            
            # Create filtercal plots if available
            # OPTIMIZATION: Filtercal data is static per cycle, so cache the Figure objects
            global _filtercal_json_cache
            cache_key = cycle_dir
            
            t_filtercal_start = time.time()
            if filtercal_data and 'pos' in filtercal_data and 'neg' in filtercal_data:
                # Check if we have cached filtercal figures for this cycle
                if cache_key in _filtercal_json_cache:
                    filtercal_pos_fig = _filtercal_json_cache[cache_key]['pos']
                    filtercal_neg_fig = _filtercal_json_cache[cache_key]['neg']
                    t_filtercal = time.time()
                    print(f"  Filtercal plots: {(t_filtercal-t_filtercal_start)*1000:.1f}ms (from cache)")
                else:
                    # Generate new filtercal plots
                    from utilities.io_utils.conversions import adc_counts_to_voltage
                    
                    filtercal_pos = filtercal_data['pos']
                    filtercal_neg = filtercal_data['neg']
                    
                    time_pos = filtercal_pos.get('timestamp', '')
                    time_neg = filtercal_neg.get('timestamp', '')
                    
                    # Convert ADC to voltage
                    volts_pos = adc_counts_to_voltage(filtercal_pos['data'], ref=5.0)
                    volts_neg = adc_counts_to_voltage(filtercal_neg['data'], ref=5.0)
                    
                    lo_pos = filtercal_pos['lo_frequencies']
                    lo_neg = filtercal_neg['lo_frequencies']
                    
                    # Create filtercal plots (static, no hover)
                    title_pos = f"+5dBm Filtercal{' - ' + time_pos if time_pos else ''}"
                    title_neg = f"-4dBm Filtercal{' - ' + time_neg if time_neg else ''}"
                    
                    # Downsample by 3x for speed
                    step = 3
                    lo_pos_sub = lo_pos[::step]
                    lo_neg_sub = lo_neg[::step]
                    volts_pos_sub = volts_pos[::step, :]
                    volts_neg_sub = volts_neg[::step, :]
                    
                    # Create positive filtercal plot
                    filtercal_pos_fig = go.Figure()
                    for filt_idx in range(21):
                        filtercal_pos_fig.add_trace(go.Scattergl(
                            x=lo_pos_sub,
                            y=volts_pos_sub[:, filt_idx],
                            mode='lines',
                            name=f'Filter {filt_idx+1}',
                            showlegend=False,
                            line=dict(width=1),
                            hoverinfo='skip'
                        ))
                    filtercal_pos_fig.update_layout(
                        title=title_pos,
                        xaxis_title="LO Frequency (MHz)",
                        yaxis_title="Voltage (V)",
                        xaxis_range=[900, 960],
                        yaxis_range=[0.8, 2.2],
                        template="plotly_white",
                        height=300,
                        margin=dict(l=50, r=20, t=40, b=40)
                    )
                    
                    # Create negative filtercal plot
                    filtercal_neg_fig = go.Figure()
                    for filt_idx in range(21):
                        filtercal_neg_fig.add_trace(go.Scattergl(
                            x=lo_neg_sub,
                            y=volts_neg_sub[:, filt_idx],
                            mode='lines',
                            name=f'Filter {filt_idx+1}',
                            showlegend=False,
                            line=dict(width=1),
                            hoverinfo='skip'
                        ))
                    filtercal_neg_fig.update_layout(
                        title=title_neg,
                        xaxis_title="LO Frequency (MHz)",
                        yaxis_title="Voltage (V)",
                        xaxis_range=[900, 960],
                        yaxis_range=[0.8, 2.2],
                        template="plotly_white",
                        height=300,
                        margin=dict(l=50, r=20, t=40, b=40)
                    )
                    
                    # Cache the figures for this cycle
                    _filtercal_json_cache[cache_key] = {
                        'pos': filtercal_pos_fig,
                        'neg': filtercal_neg_fig
                    }
                    
                    # Clear old cache entries (keep only last 3 cycles)
                    if len(_filtercal_json_cache) > 3:
                        oldest_key = list(_filtercal_json_cache.keys())[0]
                        del _filtercal_json_cache[oldest_key]
                    
                    t_filtercal = time.time()
                    print(f"  Filtercal plots: {(t_filtercal-t_filtercal_start)*1000:.1f}ms (generated)")
            else:
                # Create empty placeholder figures
                filtercal_pos_fig = go.Figure()
                filtercal_pos_fig.update_layout(
                    title="No +5dBm filtercal data",
                    template="plotly_white",
                    height=300
                )
                filtercal_neg_fig = go.Figure()
                filtercal_neg_fig.update_layout(
                    title="No -4dBm filtercal data",
                    template="plotly_white",
                    height=300
                )
                t_filtercal = time.time()
                print(f"  Filtercal plots: {(t_filtercal-t_filtercal_start)*1000:.1f}ms (no data)")
            
            t5 = time.time()
            print(f"  Create plots: {(t5-t4)*1000:.1f}ms")
            print(f"  TOTAL: {(t5-t0)*1000:.1f}ms")
            
            # Plotly config for faster rendering
            # staticPlot: true disables all interactivity, reducing JSON size
            plot_config = {
                'displayModeBar': False,
                'staticPlot': True,  # No zoom, pan, hover - pure static image
                'responsive': True
            }
            
            # Use STATIC IDs - allows Dash to update figures in-place
            # This avoids tearing down and recreating DOM on every update
            
            # 2x2 grid layout
            plot_content = html.Div([
                html.Div([
                    html.Div([
                        dcc.Graph(id='grid-voltage-graph', figure=voltage_fig, 
                                 style={'height': '350px'}, config=plot_config)
                    ], style={'display': 'inline-block', 'width': '48%', 'marginRight': '2%', 
                             'verticalAlign': 'top'}),
                    
                    html.Div([
                        dcc.Graph(id='grid-power-graph', figure=power_fig, 
                                 style={'height': '350px'}, config=plot_config)
                    ], style={'display': 'inline-block', 'width': '48%', 'verticalAlign': 'top'}),
                ], style={'marginBottom': '10px'}),
                
                html.Div([
                    html.Div([
                        # Static ID - Dash can reuse if figure object unchanged
                        dcc.Graph(id='filtercal-pos-static', figure=filtercal_pos_fig,
                                 style={'height': '350px'}, config=plot_config)
                    ], style={'display': 'inline-block', 'width': '48%', 'marginRight': '2%', 
                             'verticalAlign': 'top'}),
                    
                    html.Div([
                        # Static ID - Dash can reuse if figure object unchanged
                        dcc.Graph(id='filtercal-neg-static', figure=filtercal_neg_fig,
                                 style={'height': '350px'}, config=plot_config)
                    ], style={'display': 'inline-block', 'width': '48%', 'verticalAlign': 'top'}),
                ])
            ])
            
            # Measure JSON size after downsampling
            t_json_start = time.time()
            json_voltage = voltage_fig.to_json()
            json_power = power_fig.to_json()
            t_json_end = time.time()
            
            total_json_kb = (len(json_voltage) + len(json_power)) / 1024
            print(f"  Grid JSON serialization: {(t_json_end-t_json_start)*1000:.1f}ms")
            print(f"  Grid JSON size (voltage+power): {total_json_kb:.1f} KB")
        
        # Status and update time
        cycle_name = os.path.basename(cycle_dir)
        state_name = os.path.basename(state_file).replace('.fits', '')
        cal_status = "✓ Cal" if filtercal_data else "⚠️ No cal"
        status = f"🟢 Live | {cycle_name} | {state_name} | Spectrum {spectrum_idx+1}/{n_spectra} | {cal_status}"
        last_update = f"Updated: {datetime.now().strftime('%H:%M:%S')}"
        
        # Force garbage collection to clean up old figure objects
        gc.collect()
        
        # Track memory after cleanup
        mem_end = process.memory_info().rss / 1024 / 1024
        print(f"Memory at end: {mem_end:.1f} MB (delta: {mem_end - mem_start:+.1f} MB)")
        
        # Log total callback time
        callback_total = (time.time() - callback_start) * 1000
        print(f"\n*** CALLBACK TOTAL: {callback_total:.1f}ms ***\n")
        
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
        gc.collect()
        print(f"\n*** CALLBACK TOTAL: {(time.time() - callback_start) * 1000:.1f}ms (error) ***\n")
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
