"""
Calibration plotting functions

Create filtercal visualizations including line plots and heatmaps.
"""

import numpy as np
import plotly.graph_objs as go
from plotly.colors import qualitative
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from io_utils import adc_counts_to_voltage


def create_filtercal_line_plots(filtercal_pos, filtercal_neg, 
                                date_str="", time_pos="", time_neg=""):
    """
    Create side-by-side line plots for +5dBm and -4dBm filtercal.
    
    Shows filter responses as voltage vs LO frequency.
    
    Parameters
    ----------
    filtercal_pos : dict
        Filtercal data from load_filtercal() for positive power
    filtercal_neg : dict
        Filtercal data from load_filtercal() for negative power
    date_str : str
        Date string for title
    time_pos : str
        Time string for positive filtercal
    time_neg : str
        Time string for negative filtercal
    
    Returns
    -------
    tuple
        (fig_pos, fig_neg) - two plotly Figure objects
    """
    # Convert ADC counts to voltage (ref=5.0 for filtercal)
    volts_pos = adc_counts_to_voltage(filtercal_pos['data'], ref=5.0)
    volts_neg = adc_counts_to_voltage(filtercal_neg['data'], ref=5.0)
    
    lo_pos = filtercal_pos['lo_frequencies']
    lo_neg = filtercal_neg['lo_frequencies']
    
    # Downsample by 3x for diagnostics (balance between speed and detail)
    step = 3
    volts_pos = volts_pos[::step, :]
    volts_neg = volts_neg[::step, :]
    lo_pos = lo_pos[::step]
    lo_neg = lo_neg[::step]
    
    # Positive power plot - static for speed
    fig_pos = go.Figure()
    for filt_num in range(1, 22):  # Display as 1-21 but data is indexed 0-20
        filt_idx = filt_num - 1  # Array index 0-20
        fig_pos.add_trace(go.Scattergl(
            x=lo_pos,
            y=volts_pos[:, filt_idx],
            mode='lines',
            name=f'Filter {filt_num}',
            showlegend=False,
            line=dict(width=1),
            hoverinfo='skip'  # Disable hover for speed
        ))
    
    title_pos = f"+5 dBm Calibration - Filter Responses (Voltage)"
    if date_str:
        title_pos += f" - {date_str}"
    if time_pos:
        title_pos += f" ({time_pos})"
    
    fig_pos.update_layout(
        title=title_pos,
        xaxis_title="LO Frequency (MHz)",
        yaxis_title="Voltage (V)",
        xaxis_range=[900, 960],
        yaxis_range=[0.8, 2.2],
        template="plotly_white",
        hovermode=False,
        showlegend=False,
        height=480,
        margin=dict(b=60, l=40, r=20, t=40)
    )
    
    # Negative power plot - static for speed
    fig_neg = go.Figure()
    for filt_num in range(1, 22):  # Display as 1-21 but data is indexed 0-20
        filt_idx = filt_num - 1  # Array index 0-20
        fig_neg.add_trace(go.Scattergl(
            x=lo_neg,
            y=volts_neg[:, filt_idx],
            mode='lines',
            name=f'Filter {filt_num}',
            showlegend=False,
            line=dict(width=1),
            hoverinfo='skip'  # Disable hover for speed
        ))
    
    title_neg = f"-4 dBm Calibration - Filter Responses (Voltage)"
    if date_str:
        title_neg += f" - {date_str}"
    if time_neg:
        title_neg += f" ({time_neg})"
    
    fig_neg.update_layout(
        title=title_neg,
        xaxis_title="LO Frequency (MHz)",
        yaxis_title="Voltage (V)",
        xaxis_range=[900, 960],
        yaxis_range=[0.8, 2.2],
        template="plotly_white",
        hovermode=False,
        showlegend=False,
        height=480,
        margin=dict(b=60, l=40, r=20, t=40)
    )
    
    return fig_pos, fig_neg


def create_filtercal_heatmaps(filtercal_pos, filtercal_neg,
                              date_str="", time_pos="", time_neg=""):
    """
    Create side-by-side heatmaps for +5dBm and -4dBm filtercal.
    
    Shows filter responses as 2D heatmap (filter x LO frequency).
    Useful for spotting failed ADHATs (entire row will be off).
    
    Parameters
    ----------
    filtercal_pos : dict
        Filtercal data from load_filtercal() for positive power
    filtercal_neg : dict
        Filtercal data from load_filtercal() for negative power
    date_str : str
        Date string for title
    time_pos : str
        Time string for positive filtercal
    time_neg : str
        Time string for negative filtercal
    
    Returns
    -------
    tuple
        (fig_pos, fig_neg) - two plotly Figure objects with heatmaps
    """
    # Convert ADC counts to voltage (ref=5.0 for filtercal)
    volts_pos = adc_counts_to_voltage(filtercal_pos['data'], ref=5.0)
    volts_neg = adc_counts_to_voltage(filtercal_neg['data'], ref=5.0)
    
    lo_pos = filtercal_pos['lo_frequencies']
    lo_neg = filtercal_neg['lo_frequencies']
    
    # Transpose so filters are on Y-axis: (21 filters, n_freq)
    volts_pos_T = volts_pos.T
    volts_neg_T = volts_neg.T
    
    # Positive power heatmap
    fig_pos = go.Figure(data=go.Heatmap(
        z=volts_pos_T,
        x=lo_pos,
        y=list(range(1, 22)),  # Label as 1-21 for calibration display
        colorscale='Viridis',
        colorbar=dict(title="Voltage (V)"),
        hovertemplate='Filter: %{y}<br>' +
                      'LO: %{x:.1f} MHz<br>' +
                      'Voltage: %{z:.4f} V<br>' +
                      '<extra></extra>'
    ))
    
    title_pos = f"+5 dBm Calibration - Heatmap (Filter × Frequency)"
    if date_str:
        title_pos += f" - {date_str}"
    if time_pos:
        title_pos += f" ({time_pos})"
    
    fig_pos.update_layout(
        title=title_pos,
        xaxis_title="LO Frequency (MHz)",
        yaxis_title="Filter Number",
        template="plotly_white",
        height=480,
        margin=dict(b=60),
        yaxis=dict(
            tickmode='linear',
            tick0=0,
            dtick=1
        )
    )
    
    # Negative power heatmap
    fig_neg = go.Figure(data=go.Heatmap(
        z=volts_neg_T,
        x=lo_neg,
        y=list(range(1, 22)),  # Label as 1-21 for calibration display
        colorscale='Viridis',
        colorbar=dict(title="Voltage (V)"),
        hovertemplate='Filter: %{y}<br>' +
                      'LO: %{x:.1f} MHz<br>' +
                      'Voltage: %{z:.4f} V<br>' +
                      '<extra></extra>'
    ))
    
    title_neg = f"-4 dBm Calibration - Heatmap (Filter × Frequency)"
    if date_str:
        title_neg += f" - {date_str}"
    if time_neg:
        title_neg += f" ({time_neg})"
    
    fig_neg.update_layout(
        title=title_neg,
        xaxis_title="LO Frequency (MHz)",
        yaxis_title="Filter Number",
        template="plotly_white",
        height=480,
        margin=dict(b=60),
        yaxis=dict(
            tickmode='linear',
            tick0=0,
            dtick=1
        )
    )
    
    return fig_pos, fig_neg
