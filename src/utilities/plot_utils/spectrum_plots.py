"""
Spectrum plotting functions

Create voltage and power spectrum plots with consistent styling.
"""

import numpy as np
import plotly.graph_objs as go
from plotly.colors import qualitative


def get_filter_colors(n_filters=21):
    """
    Get consistent color palette for filters.
    
    Parameters
    ----------
    n_filters : int
        Number of filters (default: 21)
    
    Returns
    -------
    list
        List of color strings
    """
    colors = (qualitative.Dark24[:n_filters] if len(qualitative.Dark24) >= n_filters 
              else qualitative.Dark24 + qualitative.Light24[:n_filters-len(qualitative.Dark24)])
    return colors


def organize_data_by_filter(frequencies, values, filter_indices):
    """
    Organize parallel arrays by filter number.
    
    Parameters
    ----------
    frequencies : ndarray
        Sky frequencies (MHz)
    values : ndarray
        Values (voltage, power, etc.)
    filter_indices : ndarray
        Filter numbers (0-20)
    
    Returns
    -------
    dict
        Dictionary with filter numbers as keys, each containing:
        - 'freq': list of frequencies
        - 'values': list of values
    """
    filter_data = {}
    for freq, val, filt in zip(frequencies, values, filter_indices):
        if filt not in filter_data:
            filter_data[filt] = {'freq': [], 'values': []}
        filter_data[filt]['freq'].append(freq)
        filter_data[filt]['values'].append(val)
    return filter_data


def create_voltage_plot(frequencies, voltages, filter_indices, 
                       excluded_filters=None, title_suffix=""):
    """
    Create voltage spectrum plot.
    
    Parameters
    ----------
    frequencies : ndarray
        Sky frequencies (MHz)
    voltages : ndarray
        Detector voltages (V)
    filter_indices : ndarray
        Filter numbers (0-20)
    excluded_filters : list or None
        Filter indices to exclude from plot
    title_suffix : str
        Additional text for title (e.g., timestamp)
    
    Returns
    -------
    plotly.graph_objs.Figure
        Voltage plot figure
    """
    if excluded_filters is None:
        excluded_filters = []
    
    colors = get_filter_colors()
    filter_data = organize_data_by_filter(frequencies, voltages, filter_indices)
    
    fig = go.Figure()
    
    for filt_num in range(21):
        if filt_num in excluded_filters or filt_num not in filter_data:
            continue
        
        fig.add_trace(go.Scatter(
            x=filter_data[filt_num]['freq'],
            y=filter_data[filt_num]['values'],
            mode='markers',
            marker=dict(size=3, color=colors[filt_num]),
            name=f'Filter {filt_num}',
            showlegend=False,
            hovertemplate=f'<b>Filter {filt_num}</b><br>' +
                          '<b>Freq</b>: %{x:.1f} MHz<br>' +
                          '<b>Voltage</b>: %{y:.4f} V<br>' +
                          '<extra></extra>'
        ))
    
    title = f"Raw Detector Voltages{' - ' + title_suffix if title_suffix else ''}"
    
    fig.update_layout(
        title=title,
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
    
    return fig


def create_power_plot(frequencies, powers, filter_indices,
                     excluded_filters=None, title_suffix=""):
    """
    Create calibrated power spectrum plot.
    
    Parameters
    ----------
    frequencies : ndarray
        Sky frequencies (MHz)
    powers : ndarray
        Calibrated power (dBm)
    filter_indices : ndarray
        Filter numbers (0-20)
    excluded_filters : list or None
        Filter indices to exclude from plot
    title_suffix : str
        Additional text for title (e.g., timestamp)
    
    Returns
    -------
    plotly.graph_objs.Figure
        Power plot figure
    """
    if excluded_filters is None:
        excluded_filters = []
    
    colors = get_filter_colors()
    filter_data = organize_data_by_filter(frequencies, powers, filter_indices)
    
    fig = go.Figure()
    
    for filt_num in range(21):
        if filt_num in excluded_filters or filt_num not in filter_data:
            continue
        
        fig.add_trace(go.Scatter(
            x=filter_data[filt_num]['freq'],
            y=filter_data[filt_num]['values'],
            mode='markers',
            marker=dict(size=3, color=colors[filt_num]),
            name=f'Filter {filt_num}',
            showlegend=False,
            hovertemplate=f'<b>Filter {filt_num}</b><br>' +
                          '<b>Freq</b>: %{x:.1f} MHz<br>' +
                          '<b>Power</b>: %{y:.2f} dBm<br>' +
                          '<extra></extra>'
        ))
    
    title = f"Calibrated Power Spectrum{' - ' + title_suffix if title_suffix else ''}"
    
    fig.update_layout(
        title=title,
        xaxis_title="Frequency (MHz)",
        yaxis_title="Power (dBm)",
        yaxis_range=[-70, -20],
        xaxis_range=[0, 300],
        template="plotly_white",
        hovermode='closest',
        showlegend=False,
        height=480,
        margin=dict(b=60)
    )
    
    return fig
