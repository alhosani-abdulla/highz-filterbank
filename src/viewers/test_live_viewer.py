#!/usr/bin/env python3
"""
Test Live Viewer - Simplified version for debugging
"""

import os
import glob
from pathlib import Path
from datetime import datetime
from dash import Dash, dcc, html, Input, Output
import plotly.graph_objs as go

# Import utilities
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utilities import io_utils

BASE_DATA_DIR = "/media/peterson/INDURANCE/Data"

app = Dash(__name__)
app.title = "Test Live Viewer"

app.layout = html.Div([
    html.H1("Test Live Viewer - Debug Mode"),
    html.Div(id='debug-output'),
    html.Div(id='plot-output'),
    dcc.Interval(id='interval', interval=500, n_intervals=0)  # 0.5 seconds
])

@app.callback(
    [Output('debug-output', 'children'),
     Output('plot-output', 'children')],
    [Input('interval', 'n_intervals')]
)
def update(n):
    debug_info = []
    
    try:
        # Find most recent date directory (by modification time)
        date_dirs = []
        for entry in os.listdir(BASE_DATA_DIR):
            path = os.path.join(BASE_DATA_DIR, entry)
            if os.path.isdir(path) and len(entry) == 8 and entry.isdigit():
                date_dirs.append(path)
        
        if not date_dirs:
            return html.Pre("No date directories found"), html.Div("No data")
        
        # Sort by modification time, most recent first
        date_dirs.sort(key=os.path.getmtime, reverse=True)
        latest_date_dir = date_dirs[0]
        debug_info.append(f"Latest date: {os.path.basename(latest_date_dir)}")
        
        # Find cycles in latest date directory
        cycles = sorted(glob.glob(os.path.join(latest_date_dir, "Cycle_*")))
        debug_info.append(f"Found {len(cycles)} cycles")
        
        if not cycles:
            return html.Pre("\n".join(debug_info)), html.Div("No cycles found")
        
        latest_cycle = cycles[-1]
        debug_info.append(f"Latest cycle: {os.path.basename(latest_cycle)}")
        
        # Find state files
        state_files = sorted(glob.glob(os.path.join(latest_cycle, "state_*.fits")))
        debug_info.append(f"Found {len(state_files)} state files")
        
        if not state_files:
            return html.Pre("\n".join(debug_info)), html.Div("No state files found")
        
        # Try to load latest state file
        from astropy.io import fits
        for sf in reversed(state_files):
            try:
                with fits.open(sf) as hdul:
                    n_spectra = len(hdul[1].data) if hdul[1].data is not None else 0
                    if n_spectra > 0:
                        # Get file modification time
                        mod_time = os.path.getmtime(sf)
                        mod_str = datetime.fromtimestamp(mod_time).strftime('%H:%M:%S')
                        
                        debug_info.append(f"Using: {os.path.basename(sf)} ({n_spectra} spectra)")
                        debug_info.append(f"File modified: {mod_str}")
                        debug_info.append(f"Loading spectrum index: {n_spectra - 1} (most recent)")
                        
                        # Load most recent spectrum (last one in file)
                        spectrum_data = io_utils.load_state_file(sf, spectrum_index=n_spectra - 1)
                        debug_info.append(f"Loaded spectrum successfully")
                        debug_info.append(f"Timestamp: {spectrum_data.get('timestamp', 'N/A')}")
                        debug_info.append(f"Data shape: {spectrum_data['data'].shape}")
                        debug_info.append(f"LO freqs: {len(spectrum_data['lo_frequencies'])}")
                        
                        # Apply basic calibration
                        result = io_utils.apply_calibration_to_spectrum(
                            spectrum_data['data'],
                            spectrum_data['lo_frequencies'],
                            {},  # No calibration
                            return_voltages=True
                        )
                        frequencies, powers, filter_indices, voltages = result
                        debug_info.append(f"Calibration applied: {len(frequencies)} points")
                        
                        # Create simple plot
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(
                            x=frequencies,
                            y=powers,
                            mode='markers',
                            name='Power'
                        ))
                        fig.update_layout(
                            title=f"Test Plot - {os.path.basename(sf)}",
                            xaxis_title="Frequency (MHz)",
                            yaxis_title="Power (dBm)",
                            height=500
                        )
                        
                        return html.Pre("\n".join(debug_info)), dcc.Graph(figure=fig)
            except Exception as e:
                debug_info.append(f"Error with {os.path.basename(sf)}: {e}")
                continue
        
        return html.Pre("\n".join(debug_info)), html.Div("No valid data found")
        
    except Exception as e:
        debug_info.append(f"FATAL ERROR: {e}")
        import traceback
        debug_info.append(traceback.format_exc())
        return html.Pre("\n".join(debug_info)), html.Div("Error - see debug output")

if __name__ == '__main__':
    print("Starting test viewer on http://localhost:8052")
    app.run(debug=True, host='127.0.0.1', port=8052)
