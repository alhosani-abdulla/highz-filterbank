#!/usr/bin/env python3
"""
High-Z Filterbank Data Viewer

Web-based viewer for archived filterbank data using Plotly Dash.
Supports new DATA_CUBE FITS format with modular calibration and plotting.
"""

import os
import glob
import argparse
from pathlib import Path
from datetime import datetime
import numpy as np
from dash import Dash, dcc, html, Input, Output, State
import plotly.graph_objs as go

# Import utilities
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utilities import io_utils, plot_utils

# Configuration defaults
DEFAULT_DATA_DIR = "/media/peterson/INDURANCE/Data"
DEFAULT_S21_DIR = "/home/peterson/highz/highz-filterbank/characterization/s_parameters"

# Calibration alignment defaults
DEFAULT_ALIGN_FREQ_MIN = 50  # MHz
DEFAULT_ALIGN_FREQ_MAX = 80  # MHz

# Initialize Dash app
app = Dash(__name__)
app.title = "High-Z Filterbank Data Viewer"

# Layout
app.layout = html.Div([
    # Header
    html.Div([
        html.H1("High-Z Filterbank Data Viewer", 
                style={'textAlign': 'center', 'color': '#2c3e50', 'marginBottom': '10px'}),
        html.Div(id='status-info', 
                style={'textAlign': 'center', 'fontSize': '14px', 'color': '#7f8c8d'}),
    ], style={'marginBottom': '15px'}),
    
    # Navigation and controls
    html.Div([
        # Date / Cycle / State dropdowns
        html.Div([
            html.Label("Date:", style={'marginRight': '5px', 'fontWeight': 'bold'}),
            dcc.Dropdown(
                id='date-dropdown',
                placeholder='Select date...',
                style={'width': '150px'}
            ),
        ], style={'display': 'inline-block', 'marginRight': '15px'}),
        
        html.Div([
            html.Label("Cycle:", style={'marginRight': '5px', 'fontWeight': 'bold'}),
            dcc.Dropdown(
                id='cycle-dropdown',
                placeholder='Select cycle...',
                style={'width': '200px'}
            ),
        ], style={'display': 'inline-block', 'marginRight': '15px'}),
        
        html.Div([
            html.Label("State:", style={'marginRight': '5px', 'fontWeight': 'bold'}),
            dcc.Dropdown(
                id='state-dropdown',
                placeholder='Select state...',
                style={'width': '150px'}
            ),
        ], style={'display': 'inline-block', 'marginRight': '15px'}),
        
        html.Button('Load', id='load-button', n_clicks=0,
                   style={'padding': '8px 20px', 'backgroundColor': '#3498db', 
                          'color': 'white', 'border': 'none', 'borderRadius': '4px',
                          'cursor': 'pointer', 'verticalAlign': 'bottom'}),
    ], style={'padding': '10px', 'backgroundColor': '#ecf0f1', 'borderRadius': '4px',
              'marginBottom': '10px'}),
    
    # Spectrum slider (for files with multiple spectra)
    html.Div([
        html.Label("Spectrum:", style={'marginRight': '10px', 'fontWeight': 'bold'}),
        dcc.Slider(
            id='spectrum-slider',
            min=0,
            max=0,
            value=0,
            step=1,
            marks={},
            tooltip={"placement": "bottom", "always_visible": False}
        ),
    ], id='spectrum-slider-container', 
       style={'padding': '10px', 'backgroundColor': '#ecf0f1', 
              'borderRadius': '4px', 'marginBottom': '10px', 'display': 'none'}),
    
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
            
            # Alignment frequency range
            html.Div([
                html.Label("Alignment Region:", style={'fontWeight': 'bold', 'marginRight': '10px'}),
                dcc.Input(
                    id='align-freq-min',
                    type='number',
                    value=DEFAULT_ALIGN_FREQ_MIN,
                    style={'width': '80px', 'marginRight': '5px'}
                ),
                html.Span(" to ", style={'marginRight': '5px'}),
                dcc.Input(
                    id='align-freq-max',
                    type='number',
                    value=DEFAULT_ALIGN_FREQ_MAX,
                    style={'width': '80px', 'marginRight': '5px'}
                ),
                html.Span(" MHz", style={'fontSize': '12px', 'color': '#7f8c8d'}),
            ]),
        ], style={'padding': '10px'})
    ], style={'marginBottom': '15px', 'backgroundColor': '#ecf0f1', 
              'borderRadius': '4px', 'padding': '10px'}),
    
    # Plot containers
    html.Div(id='plot-container'),
    
    # Data stores
    dcc.Store(id='data-dir-store', data=DEFAULT_DATA_DIR),
    dcc.Store(id='s21-dir-store', data=DEFAULT_S21_DIR),
    dcc.Store(id='loaded-spectrum-data'),
    dcc.Store(id='loaded-filtercal-data'),
])


def find_available_dates(data_dir):
    """Scan data directory for available date folders (MMddyyyy format)"""
    dates = []
    if os.path.exists(data_dir):
        for entry in os.listdir(data_dir):
            path = os.path.join(data_dir, entry)
            if os.path.isdir(path):
                try:
                    if len(entry) == 8 and entry.isdigit():
                        mm, dd, yyyy = entry[:2], entry[2:4], entry[4:8]
                        datetime.strptime(f"{yyyy}-{mm}-{dd}", '%Y-%m-%d')
                        dates.append(entry)
                except (ValueError, IndexError):
                    pass
    dates.sort(reverse=True, key=lambda x: (x[4:8], x[:2], x[2:4]))
    return dates


def find_cycles_for_date(data_dir, date_folder):
    """Find all cycle directories for a given date"""
    date_path = os.path.join(data_dir, date_folder)
    if not os.path.exists(date_path):
        return []
    
    cycles = []
    for entry in os.listdir(date_path):
        path = os.path.join(date_path, entry)
        if os.path.isdir(path) and entry.startswith("Cycle_"):
            cycles.append(entry)
    
    cycles.sort()
    return cycles


def find_state_files(cycle_dir):
    """Find all state FITS files in a cycle directory"""
    state_files = glob.glob(os.path.join(cycle_dir, "state_*.fits"))
    state_files = [f for f in state_files if os.path.getsize(f) > 0]
    state_files.sort()
    return state_files


def find_filtercal_files(cycle_dir):
    """Find filtercal FITS files in a cycle directory"""
    filtercal_files = {
        'pos': None,
        'neg': None
    }
    
    for f in glob.glob(os.path.join(cycle_dir, "filtercal_*.fits")):
        if os.path.getsize(f) == 0:
            continue
        basename = os.path.basename(f)
        if "+5" in basename or "pos" in basename.lower():
            filtercal_files['pos'] = f
        elif "-4" in basename or "neg" in basename.lower():
            filtercal_files['neg'] = f
    
    return filtercal_files


@app.callback(
    Output('date-dropdown', 'options'),
    Input('data-dir-store', 'data')
)
def update_date_options(data_dir):
    """Populate date dropdown"""
    dates = find_available_dates(data_dir)
    return [{'label': d, 'value': d} for d in dates]


@app.callback(
    Output('cycle-dropdown', 'options'),
    [Input('date-dropdown', 'value')],
    [State('data-dir-store', 'data')]
)
def update_cycle_options(selected_date, data_dir):
    """Populate cycle dropdown based on selected date"""
    if not selected_date:
        return []
    cycles = find_cycles_for_date(data_dir, selected_date)
    return [{'label': c, 'value': c} for c in cycles]


@app.callback(
    Output('state-dropdown', 'options'),
    [Input('cycle-dropdown', 'value'),
     Input('date-dropdown', 'value')],
    [State('data-dir-store', 'data')]
)
def update_state_options(selected_cycle, selected_date, data_dir):
    """Populate state dropdown based on selected cycle"""
    if not selected_cycle or not selected_date:
        return []
    
    cycle_dir = os.path.join(data_dir, selected_date, selected_cycle)
    state_files = find_state_files(cycle_dir)
    
    # Extract state numbers from filenames
    states = []
    for f in state_files:
        basename = os.path.basename(f)
        # Extract state number from "state_X.fits"
        try:
            state_num = basename.split('_')[1].split('.')[0]
            states.append({'label': f'State {state_num}', 'value': basename})
        except (IndexError, ValueError):
            pass
    
    return states


@app.callback(
    [Output('loaded-spectrum-data', 'data'),
     Output('loaded-filtercal-data', 'data'),
     Output('spectrum-slider-container', 'style'),
     Output('spectrum-slider', 'max'),
     Output('spectrum-slider', 'marks'),
     Output('status-info', 'children')],
    [Input('load-button', 'n_clicks')],
    [State('date-dropdown', 'value'),
     State('cycle-dropdown', 'value'),
     State('state-dropdown', 'value'),
     State('data-dir-store', 'data'),
     State('s21-dir-store', 'data'),
     State('calibration-toggles', 'value')]
)
def load_data(n_clicks, selected_date, selected_cycle, selected_state,
              data_dir, s21_dir, calib_toggles):
    """Load spectrum and filtercal data"""
    
    if not selected_date or not selected_cycle or not selected_state or n_clicks == 0:
        slider_style = {'padding': '10px', 'backgroundColor': '#ecf0f1', 
                       'borderRadius': '4px', 'marginBottom': '10px', 'display': 'none'}
        return None, None, slider_style, 0, {}, "Select date, cycle, and state to load data"
    
    # Construct paths
    cycle_dir = os.path.join(data_dir, selected_date, selected_cycle)
    state_file = os.path.join(cycle_dir, selected_state)
    
    if not os.path.exists(state_file):
        slider_style = {'padding': '10px', 'backgroundColor': '#ecf0f1', 
                       'borderRadius': '4px', 'marginBottom': '10px', 'display': 'none'}
        return None, None, slider_style, 0, {}, f"❌ File not found: {selected_state}"
    
    try:
        # Load state file (spectrum 0 initially)
        spectrum_data = io_utils.load_state_file(state_file, spectrum_index=0)
        n_spectra = spectrum_data['n_spectra']
        
        # Find and load filtercal files
        filtercal_files = find_filtercal_files(cycle_dir)
        filtercal_data = None
        
        if filtercal_files['pos'] and filtercal_files['neg']:
            filtercal_pos = io_utils.load_filtercal(filtercal_files['pos'])
            filtercal_neg = io_utils.load_filtercal(filtercal_files['neg'])
            
            # Load S21 corrections if enabled
            s21_data = None
            if 's21' in calib_toggles:
                s21_data = io_utils.load_s21_corrections(s21_dir)
            
            # Build calibration
            filter_cal = io_utils.build_filter_calibration(
                filtercal_pos, filtercal_neg,
                s21_data=s21_data
            )
            
            filtercal_data = {
                'pos': filtercal_pos,
                'neg': filtercal_neg,
                'calibration': filter_cal
            }
        
        # Slider configuration
        slider_style = {'padding': '10px', 'backgroundColor': '#ecf0f1', 
                       'borderRadius': '4px', 'marginBottom': '10px'}
        if n_spectra == 1:
            slider_style['display'] = 'none'
        
       # Create slider marks (show every 10th or fewer if many spectra)
        step = max(1, n_spectra // 10)
        marks = {i: str(i) for i in range(0, n_spectra, step)}
        if (n_spectra - 1) not in marks:
            marks[n_spectra - 1] = str(n_spectra - 1)
        
        # Status message
        cal_status = "✓ Calibrated" if filtercal_data else "⚠️ No calibration"
        status = (f"Loaded: {selected_state} | Cycle: {selected_cycle} | "
                 f"Spectra: {n_spectra} | {cal_status}")
        
        # Store only file paths and metadata (JSON-serializable)
        spectrum_storage = {
            'filepath': state_file,
            'n_spectra': n_spectra,
            'current_spectrum_index': 0
        }
        
        filtercal_storage = {
            'pos_file': filtercal_files['pos'],
            'neg_file': filtercal_files['neg'],
            'has_calibration': filtercal_data is not None
        } if filtercal_files['pos'] and filtercal_files['neg'] else None
        
        return spectrum_storage, filtercal_storage, slider_style, n_spectra - 1, marks, status
        
    except Exception as e:
        slider_style = {'padding': '10px', 'backgroundColor': '#ecf0f1', 
                       'borderRadius': '4px', 'marginBottom': '10px', 'display': 'none'}
        return None, None, slider_style, 0, {}, f"❌ Error loading data: {str(e)}"


@app.callback(
    Output('loaded-spectrum-data', 'data', allow_duplicate=True),
    [Input('spectrum-slider', 'value')],
    [State('loaded-spectrum-data', 'data')],
    prevent_initial_call=True
)
def update_spectrum_index(spectrum_idx, spectrum_storage):
    """Update spectrum index when slider changes"""
    if not spectrum_storage or spectrum_idx is None:
        return spectrum_storage
    
    # Just update the index - data will be reloaded when creating plots
    spectrum_storage['current_spectrum_index'] = spectrum_idx
    return spectrum_storage


@app.callback(
    Output('plot-container', 'children'),
    [Input('loaded-spectrum-data', 'data'),
     Input('loaded-filtercal-data', 'data'),
     Input('view-mode', 'value'),
     Input('filtercal-mode', 'value'),
     Input('calibration-toggles', 'value'),
     Input('filter-exclusions', 'value'),
     Input('align-freq-min', 'value'),
     Input('align-freq-max', 'value')]
)
def create_plots(spectrum_storage, filtercal_storage, view_mode, filtercal_mode,
                calib_toggles, filter_exclusions_str, align_freq_min, align_freq_max):
    """Generate plots based on loaded data and settings"""
    
    if not spectrum_storage:
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title="No data loaded",
            template="plotly_white",
            height=400
        )
        return html.Div([dcc.Graph(figure=empty_fig)])
    
    # Load the spectrum data
    try:
        filepath = spectrum_storage['filepath']
        spectrum_idx = spectrum_storage['current_spectrum_index']
        spectrum_data = io_utils.load_state_file(filepath, spectrum_index=spectrum_idx)
    except Exception as e:
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title=f"Error loading spectrum: {str(e)}",
            template="plotly_white",
            height=400
        )
        return html.Div([dcc.Graph(figure=empty_fig)])
    
    # Parse filter exclusions
    excluded_filters = []
    if filter_exclusions_str:
        try:
            excluded_filters = [int(x.strip()) for x in filter_exclusions_str.split(',') if x.strip()]
        except ValueError:
            pass
    
    # Load calibration if available
    filter_cal = None
    filtercal_pos = None
    filtercal_neg = None
    
    if filtercal_storage and filtercal_storage['has_calibration']:
        try:
            filtercal_pos = io_utils.load_filtercal(filtercal_storage['pos_file'])
            filtercal_neg = io_utils.load_filtercal(filtercal_storage['neg_file'])
            
            # Load S21 corrections if enabled
            s21_data = None
            if 's21' in calib_toggles:
                from pathlib import Path
                s21_dir = Path(__file__).parent.parent.parent / "characterization" / "s_parameters"
                s21_data = io_utils.load_s21_corrections(str(s21_dir))
            
            # Build calibration
            filter_cal = io_utils.build_filter_calibration(
                filtercal_pos, filtercal_neg,
                s21_data=s21_data
            )
        except Exception as e:
            print(f"Error loading calibration: {e}")
    
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
            freq_min=align_freq_min or DEFAULT_ALIGN_FREQ_MIN,
            freq_max=align_freq_max or DEFAULT_ALIGN_FREQ_MAX,
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
        
        return html.Div([
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
        if filtercal_pos and filtercal_neg:
            # Extract timestamps from filtercal metadata
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
            # Empty plots if no filtercal
            fig_pos = go.Figure()
            fig_pos.update_layout(title="No +5dBm filtercal available", template="plotly_white")
            fig_neg = go.Figure()
            fig_neg.update_layout(title="No -4dBm filtercal available", template="plotly_white")
        
        # 2x2 grid layout
        return html.Div([
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='High-Z Filterbank Data Viewer')
    parser.add_argument('--data-dir', default=DEFAULT_DATA_DIR,
                       help=f'Data directory (default: {DEFAULT_DATA_DIR})')
    parser.add_argument('--s21-dir', default=DEFAULT_S21_DIR,
                       help=f'S21 corrections directory (default: {DEFAULT_S21_DIR})')
    parser.add_argument('--port', type=int, default=8050,
                       help='Port to run server on (default: 8050)')
    
    args = parser.parse_args()
    
    # Update stores with command-line args
    DEFAULT_DATA_DIR = args.data_dir
    DEFAULT_S21_DIR = args.s21_dir
    
    print("\n" + "="*60)
    print("High-Z Filterbank Data Viewer")
    print("="*60)
    print(f"\nData directory: {args.data_dir}")
    print(f"S21 directory: {args.s21_dir}")
    print("\nStarting server...")
    print(f"\nAccess the dashboard at:")
    print(f"  http://localhost:{args.port}")
    print("\nPress Ctrl+C to stop")
    print("="*60 + "\n")
    
    app.run(debug=False, host='127.0.0.1', port=args.port)
