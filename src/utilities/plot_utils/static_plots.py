"""
Static plot generation using matplotlib for fast server-side rendering.

Creates PNG images instead of interactive Plotly figures to avoid
JSON serialization overhead on Raspberry Pi.
"""

import io
import base64
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgb


def get_filter_colors_mpl(n_filters=21):
    """Get matplotlib color cycle for filters."""
    # Use tab20 + one extra color from tab20b to get 21 colors
    colors = list(plt.cm.tab20.colors)
    if n_filters > 20:
        colors.extend(list(plt.cm.tab20b.colors[:n_filters-20]))
    return colors[:n_filters]


def create_voltage_plot_static(frequencies, voltages, filter_indices, 
                               excluded_filters=None, title_suffix=""):
    """
    Create static voltage spectrum plot as PNG.
    
    Returns base64-encoded PNG image string.
    """
    if excluded_filters is None:
        excluded_filters = []
    
    colors = get_filter_colors_mpl()
    
    # Organize data by filter
    filter_data = {}
    for freq, volt, filt in zip(frequencies, voltages, filter_indices):
        if filt in excluded_filters:
            continue
        filt_num = int(filt) + 1  # 1-indexed
        if filt_num not in filter_data:
            filter_data[filt_num] = {'freq': [], 'values': []}
        filter_data[filt_num]['freq'].append(freq)
        filter_data[filt_num]['values'].append(volt)
    
    # Create plot
    fig, ax = plt.subplots(figsize=(8, 5), dpi=100)
    
    for filt_num in range(1, 22):
        if filt_num not in filter_data:
            continue
        ax.plot(filter_data[filt_num]['freq'], 
                filter_data[filt_num]['values'],
                'o', markersize=2, color=colors[filt_num-1], 
                alpha=0.7)
    
    title = f"Raw Detector Voltages{' - ' + title_suffix if title_suffix else ''}"
    ax.set_title(title, fontsize=11)
    ax.set_xlabel("Frequency (MHz)", fontsize=10)
    ax.set_ylabel("Voltage (V)", fontsize=10)
    ax.set_xlim(0, 350)
    ax.set_ylim(0.8, 2.2)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # Convert to base64 PNG
    buf = io.BytesIO()
    try:
        fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        buf.seek(0)
        img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    finally:
        buf.close()
        plt.close(fig)
    
    return img_base64


def create_power_plot_static(frequencies, powers, filter_indices,
                             excluded_filters=None, title_suffix=""):
    """
    Create static power spectrum plot as PNG.
    
    Returns base64-encoded PNG image string.
    """
    if excluded_filters is None:
        excluded_filters = []
    
    colors = get_filter_colors_mpl()
    
    # Organize data by filter
    filter_data = {}
    for freq, power, filt in zip(frequencies, powers, filter_indices):
        if filt in excluded_filters:
            continue
        filt_num = int(filt) + 1  # 1-indexed
        if filt_num not in filter_data:
            filter_data[filt_num] = {'freq': [], 'values': []}
        filter_data[filt_num]['freq'].append(freq)
        filter_data[filt_num]['values'].append(power)
    
    # Create plot
    fig, ax = plt.subplots(figsize=(8, 5), dpi=100)
    
    for filt_num in range(1, 22):
        if filt_num not in filter_data:
            continue
        ax.plot(filter_data[filt_num]['freq'], 
                filter_data[filt_num]['values'],
                'o', markersize=2, color=colors[filt_num-1],
                alpha=0.7)
    
    title = f"Calibrated Power Spectrum{' - ' + title_suffix if title_suffix else ''}"
    ax.set_title(title, fontsize=11)
    ax.set_xlabel("Frequency (MHz)", fontsize=10)
    ax.set_ylabel("Power (dBm)", fontsize=10)
    ax.set_xlim(-50, 350)
    ax.set_ylim(-80, 20)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # Convert to base64 PNG
    buf = io.BytesIO()
    try:
        fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        buf.seek(0)
        img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    finally:
        buf.close()
        plt.close(fig)
    
    return img_base64


def create_filtercal_plot_static(lo_frequencies, voltages, title):
    """
    Create static filtercal diagnostic plot as PNG.
    
    Parameters
    ----------
    lo_frequencies : ndarray
        LO frequencies (MHz)
    voltages : ndarray (n_lo, 21)
        Voltages for all 21 filters
    title : str
        Plot title
    
    Returns base64-encoded PNG image string.
    """
    colors = get_filter_colors_mpl()
    
    # Create plot
    fig, ax = plt.subplots(figsize=(8, 5), dpi=100)
    
    # Downsample for speed
    step = 3
    lo_sub = lo_frequencies[::step]
    volts_sub = voltages[::step, :]
    
    for filt_idx in range(21):
        ax.plot(lo_sub, volts_sub[:, filt_idx],
                linewidth=1, color=colors[filt_idx],
                alpha=0.8)
    
    ax.set_title(title, fontsize=11)
    ax.set_xlabel("LO Frequency (MHz)", fontsize=10)
    ax.set_ylabel("Voltage (V)", fontsize=10)
    ax.set_xlim(900, 960)
    ax.set_ylim(0.8, 2.2)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # Convert to base64 PNG
    buf = io.BytesIO()
    try:
        fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        buf.seek(0)
        img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    finally:
        buf.close()
        plt.close(fig)
    
    return img_base64
