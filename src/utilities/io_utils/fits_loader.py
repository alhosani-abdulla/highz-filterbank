"""
FITS file loading utilities for new DATA_CUBE format

Loads filtercal and state files with the new image cube data structure.
"""

import numpy as np
from astropy.io import fits
from pathlib import Path


def get_filter_centers(num_filters=21, start_mhz=904.0, step_mhz=2.6):
    """
    Get center frequencies for filterbank.
    
    Parameters
    ----------
    num_filters : int
        Number of filters (default: 21)
    start_mhz : float
        Starting center frequency in MHz (default: 904.0)
    step_mhz : float
        Frequency step between filters in MHz (default: 2.6)
    
    Returns
    -------
    centers : ndarray
        Center frequencies in MHz (num_filters,)
    """
    return start_mhz + step_mhz * np.arange(num_filters)


def load_filtercal(filepath):
    """
    Load a filtercal FITS file (new DATA_CUBE format).
    
    Format: DATA_CUBE is a flat 1D array that must be reshaped to (n_freq, n_channels)
    
    Parameters
    ----------
    filepath : str or Path
        Path to filtercal FITS file (e.g., filtercal_+5dBm.fits)
    
    Returns
    -------
    dict with keys:
        'lo_frequencies' : ndarray (n_freq,) - LO sweep frequencies in MHz
        'data' : ndarray (n_freq, 21) - ADC counts for 21 filter channels
        'n_freq' : int - number of LO frequency points
        'n_channels' : int - number of filter channels (21)
        'state' : str - state identifier (e.g., 'filtercal_+5dBm')
        'timestamp' : str - acquisition timestamp
        'metadata' : dict - all PRIMARY HDU header items
    """
    with fits.open(filepath) as hdul:
        # Primary HDU has metadata
        primary_hdr = hdul[0].header
        
        # Binary table HDU has data
        table = hdul[1].data
        
        # Extract metadata from primary header
        n_lo_pts = primary_hdr.get('N_LO_PTS', 0)
        n_filters = primary_hdr.get('N_FILTERS', 21)
        state = primary_hdr.get('STATE', 'unknown')
        timestamp = primary_hdr.get('TIMESTAMP', '')
        
        # Load LO frequencies (MHz)
        lo_frequencies = table['LO_FREQUENCIES'][0]  # Should be (n_freq,) array
        
        # Load DATA_CUBE and reshape
        data_cube_flat = table['DATA_CUBE'][0]  # Flat 1D array
        expected_size = n_lo_pts * n_filters
        
        if len(data_cube_flat) != expected_size:
            raise ValueError(
                f"DATA_CUBE size mismatch: got {len(data_cube_flat)}, "
                f"expected {n_lo_pts} × {n_filters} = {expected_size}"
            )
        
        # Reshape: (n_freq, n_channels)
        # Packing is frequency-major: [freq0_ch0...ch20, freq1_ch0...ch20, ...]
        data_2d = data_cube_flat.reshape(n_lo_pts, n_filters)
        
        # Collect all metadata
        metadata = dict(primary_hdr)
        
        return {
            'lo_frequencies': lo_frequencies,
            'data': data_2d,
            'n_freq': n_lo_pts,
            'n_channels': n_filters,
            'state': state,
            'timestamp': timestamp,
            'metadata': metadata
        }


def load_state_file(filepath, spectrum_index=0):
    """
    Load a state file (new DATA_CUBE format).
    
    State files can contain multiple spectra. Each spectrum has its own
    DATA_CUBE entry, timestamp, and LO_FREQUENCIES array.
    
    Parameters
    ----------
    filepath : str or Path
        Path to state FITS file (e.g., state_1.fits)
    spectrum_index : int
        Which spectrum to load (default: 0 for first)
    
    Returns
    -------
    dict with keys:
        'lo_frequencies' : ndarray (n_freq,) - LO sweep frequencies in MHz
        'data' : ndarray (n_freq, 21) - ADC counts for 21 filter channels
        'n_freq' : int - number of LO frequency points
        'n_channels' : int - number of filter channels (21)
        'state' : int or str - state number
        'cycle_id' : str - cycle identifier
        'timestamp' : str - spectrum acquisition timestamp
        'n_spectra' : int - total number of spectra in file
        'metadata' : dict - all PRIMARY HDU header items
    """
    with fits.open(filepath) as hdul:
        # Primary HDU has metadata
        primary_hdr = hdul[0].header
        
        # Binary table HDU has data (one row per spectrum)
        table = hdul[1].data
        
        # Extract metadata from primary header
        n_lo_pts = primary_hdr.get('N_LO_PTS', 0)
        n_filters = primary_hdr.get('N_FILTERS', 21)
        state = primary_hdr.get('STATE', 'unknown')
        cycle_id = primary_hdr.get('CYCLE_ID', '')
        n_spectra = primary_hdr.get('N_SPECTRA', len(table))
        
        if spectrum_index >= n_spectra:
            raise ValueError(
                f"Spectrum index {spectrum_index} out of range "
                f"(file has {n_spectra} spectra)"
            )
        
        # Load data for requested spectrum
        row = table[spectrum_index]
        
        lo_frequencies = row['LO_FREQUENCIES']  # (n_freq,) array
        data_cube_flat = row['DATA_CUBE']  # Flat 1D array
        spectrum_timestamp = row['SPECTRUM_TIMESTAMP']
        
        expected_size = n_lo_pts * n_filters
        
        if len(data_cube_flat) != expected_size:
            raise ValueError(
                f"DATA_CUBE size mismatch: got {len(data_cube_flat)}, "
                f"expected {n_lo_pts} × {n_filters} = {expected_size}"
            )
        
        # Reshape: (n_freq, n_channels)
        data_2d = data_cube_flat.reshape(n_lo_pts, n_filters)
        
        # Collect all metadata
        metadata = dict(primary_hdr)
        
        return {
            'lo_frequencies': lo_frequencies,
            'data': data_2d,
            'n_freq': n_lo_pts,
            'n_channels': n_filters,
            'state': state,
            'cycle_id': cycle_id,
            'timestamp': spectrum_timestamp,
            'n_spectra': n_spectra,
            'metadata': metadata
        }


def find_closest_lo_row(lo_frequencies, target_freq):
    """
    Find the row index with LO frequency closest to target.
    
    Parameters
    ----------
    lo_frequencies : ndarray
        Array of LO frequencies (MHz)
    target_freq : float
        Target frequency (MHz)
    
    Returns
    -------
    int
        Row index of closest LO frequency
    """
    distances = np.abs(lo_frequencies - target_freq)
    return int(np.argmin(distances))
