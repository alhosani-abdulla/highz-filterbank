"""FITS loading and spectrum-preparation utilities.

This module provides helpers to:
- Load filtercal and state FITS files stored in the DATA_CUBE schema.
- Build and cache detector calibration objects for a cycle.
- Prepare calibrated spectrum arrays for plotting/analysis.
"""

import numpy as np
from astropy.io import fits
from pathlib import Path
import os
import time
import logging
from utilities import io_utils

# Import utilities
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from .VARS import *

logger = logging.getLogger(__name__)

# Cache key: (cycle_dir, apply_s21) -> prepared calibration payload or None
_calibration_cache = {}

def load_calibration_data(cycle_dir, s21_dir=DEFAULT_S21_DIR, apply_s21=True):
    """Load and cache calibration artifacts for one acquisition cycle.

    Parameters
    ----------
    cycle_dir : str or Path
        Cycle directory expected to contain ``filtercal_+5dBm.fits`` and
        ``filtercal_-4dBm.fits``.
    s21_dir : str or Path
        Directory containing S21 correction files. Only used when
        ``apply_s21`` is True.
    apply_s21 : bool
        If True, apply S21 correction when building detector calibration.

    Returns
    -------
    dict or None
        Returns a dictionary with keys ``pos``, ``neg``, and ``calibration``
        when calibration files are available and valid. Returns None if
        files are missing/empty or calibration build fails. None results are
        cached to avoid repeated I/O on subsequent calls.

    Notes
    -----
    Cache size is capped to 3 entries to bound memory usage.
    """
    global _calibration_cache
    
    # Create cache key
    cache_key = (cycle_dir, apply_s21)
    
    # Check cache first
    if cache_key in _calibration_cache:
        return _calibration_cache[cache_key]
    
    # Check that required filtercal files exist
    filtercal_pos_file = os.path.join(cycle_dir, "filtercal_+5dBm.fits")
    filtercal_neg_file = os.path.join(cycle_dir, "filtercal_-4dBm.fits")
    
    if not os.path.exists(filtercal_pos_file) or not os.path.exists(filtercal_neg_file):
        # Cache None result too to avoid repeated checks
        _calibration_cache[cache_key] = None
        return None
    
    if os.path.getsize(filtercal_pos_file) == 0 or os.path.getsize(filtercal_neg_file) == 0:
        _calibration_cache[cache_key] = None
        return None
    
    try:
        logger.info("Loading calibration for %s...", os.path.basename(cycle_dir))
        
        # Load raw filtercal data for diagnostic plots
        filtercal_pos = io_utils.load_filtercal(filtercal_pos_file)
        filtercal_neg = io_utils.load_filtercal(filtercal_neg_file)
        
        # Use the new FilterDetectorCalibration which properly accounts for
        # LO power variation with frequency
        filter_cal = io_utils.build_filter_detector_calibration(
            cycle_dir=cycle_dir,
            apply_s21=apply_s21,
            s21_dir=s21_dir if apply_s21 else None
        )
        
        # Print calibration info on first load
        filter_cal.info()
        
        result = {
            'pos': filtercal_pos,
            'neg': filtercal_neg,
            'calibration': filter_cal
        }
        
        # Cache the result
        _calibration_cache[cache_key] = result
        logger.info("Calibration cached for %s", os.path.basename(cycle_dir))
        
        # Keep cache size reasonable (max 3 cycles)
        if len(_calibration_cache) > 3:
            # Remove oldest entry
            oldest_key = next(iter(_calibration_cache))
            del _calibration_cache[oldest_key]
        
        return result
        
    except Exception:
        logger.exception("Error loading calibration")
        _calibration_cache[cache_key] = None
        return None

def load_prepared_spectrum_data(
    state_file,
    spectrum_idx,
    cycle_dir,
    filter_exclusions_str,
    align_freq_min=DEFAULT_ALIGN_FREQ_MIN,
    align_freq_max=DEFAULT_ALIGN_FREQ_MAX,
    s21_dir = DEFAULT_S21_DIR,
    calib_toggles=['s21', 'alignment']
):
    """Load one spectrum and return calibrated arrays ready for plotting.

    Parameters
    ----------
    state_file : str or Path
        Path to a state FITS file.
    spectrum_idx : int
        Zero-based spectrum index within ``state_file``.
    cycle_dir : str or Path
        Cycle directory containing calibration FITS files.
    s21_dir : str or Path
        Directory with S21 correction data.
    calib_toggles : list[str]
        UI toggle values. Supported flags are ``"s21"`` and ``"alignment"``.
    filter_exclusions_str : str or None
        Comma-separated filter indices to exclude from normalization.
    align_freq_min : float
        Lower bound (MHz) for alignment normalization window.
    align_freq_max : float
        Upper bound (MHz) for alignment normalization window.

    Returns
    -------
    dict
        Dictionary containing:
        - ``frequencies``: LO frequencies (MHz)
        - ``powers``: calibrated/normalized power values
        - ``filter_indices``: filter ID per point
        - ``voltages``: calibrated voltages
        - ``excluded_filters``: parsed exclusions as list[int]
        - ``filtercal_data``: calibration payload or None
        - ``time_display``: HH:MM:SS string when timestamp is parseable
        - ``t0`` and ``t4``: timing markers used by caller logs

    Notes
    -----
    This helper intentionally keeps debug timing prints to match existing
    live viewer profiling behavior.
    """
    t0 = time.time()

    spectrum_data = io_utils.load_state_file(state_file, spectrum_index=spectrum_idx)
    t1 = time.time()
    logger.debug("  Load spectrum: %.1fms", (t1 - t0) * 1000)

    apply_s21 = 's21' in calib_toggles
    filtercal_data = load_calibration_data(cycle_dir, s21_dir, apply_s21)
    filter_cal = filtercal_data.get('calibration') if filtercal_data else None
    t2 = time.time()
    logger.debug("  Load calibration: %.1fms", (t2 - t1) * 1000)

    excluded_filters = []
    if filter_exclusions_str:
        try:
            excluded_filters = [int(x.strip()) for x in filter_exclusions_str.split(',') if x.strip()]
        except ValueError:
            pass

    result = io_utils.apply_calibration_to_spectrum(
        spectrum_data['data'],
        spectrum_data['lo_frequencies'],
        filter_cal if filter_cal else {},
        return_voltages=True,
    )
    frequencies, powers, filter_indices, voltages = result
    t3 = time.time()
    logger.debug("  Apply calibration: %.1fms", (t3 - t2) * 1000)
    logger.debug(
        "  Data shape: %d total points, %d unique filters",
        len(frequencies),
        len(set(filter_indices)),
    )

    if 'alignment' in calib_toggles and filter_cal:
        normalization = io_utils.calculate_filter_normalization(
            frequencies,
            powers,
            filter_indices,
            freq_min=align_freq_min,
            freq_max=align_freq_max,
            excluded_filters=excluded_filters,
        )
        if normalization:
            powers_normalized = []
            for power, filt in zip(powers, filter_indices):
                if filt in normalization:
                    powers_normalized.append(power + normalization[filt])
                else:
                    powers_normalized.append(power)
            powers = np.array(powers_normalized)

    t4 = time.time()
    if 'alignment' in calib_toggles and filter_cal:
        logger.debug("  Normalization: %.1fms", (t4 - t3) * 1000)

    timestamp = spectrum_data.get('timestamp', '')
    if isinstance(timestamp, str) and len(timestamp) >= 14:
        time_display = f"{timestamp[8:10]}:{timestamp[10:12]}:{timestamp[12:14]}"
    else:
        time_display = str(timestamp)

    return {
        'frequencies': frequencies,
        'powers': powers,
        'filter_indices': filter_indices,
        'voltages': voltages,
        'excluded_filters': excluded_filters,
        'filtercal_data': filtercal_data,
        'time_display': time_display,
        't0': t0,
        't4': t4,
    }

def get_filter_centers(num_filters=21, start_mhz=904.0, step_mhz=2.6):
    """Return nominal center frequencies for evenly spaced filter channels.

    Parameters
    ----------
    num_filters : int, optional
        Number of filters/channels. Default is 21.
    start_mhz : float, optional
        Center frequency of filter index 0 in MHz. Default is 904.0.
    step_mhz : float, optional
        Frequency spacing between adjacent filter centers in MHz.
        Default is 2.6.

    Returns
    -------
    ndarray
        One-dimensional array of shape ``(num_filters,)`` in MHz.
    """
    return start_mhz + step_mhz * np.arange(num_filters)


def load_filtercal(filepath):
    """Load a filtercal FITS file using the DATA_CUBE layout.

    Expected FITS structure:
    - PRIMARY HDU: metadata headers (for example ``N_LO_PTS``, ``N_FILTERS``)
    - HDU 1 table: ``LO_FREQUENCIES`` and flat ``DATA_CUBE`` arrays

    ``DATA_CUBE`` is reshaped to ``(n_lo_pts, n_filters)`` where rows are
    LO frequency points and columns are filter channels.

    Parameters
    ----------
    filepath : str or Path
        Path to filtercal FITS file (for example ``filtercal_+5dBm.fits``).

    Returns
    -------
    dict
        Keys include ``lo_frequencies``, ``data``, ``n_freq``, ``n_channels``,
        ``state``, ``timestamp``, and ``metadata``.

    Raises
    ------
    ValueError
        If flattened ``DATA_CUBE`` length does not match
        ``n_lo_pts * n_filters`` from headers.
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
    """Load one spectrum from a state FITS file using the DATA_CUBE layout.

    State files can contain multiple spectra (one row per spectrum in HDU 1).

    Parameters
    ----------
    filepath : str or Path
        Path to state FITS file (for example ``state_1.fits``).
    spectrum_index : int, optional
        Zero-based row index of spectrum to load. Default is 0.

    Returns
    -------
    dict
        Keys include ``lo_frequencies``, ``data``, ``n_freq``, ``n_channels``,
        ``state``, ``cycle_id``, ``timestamp``, ``n_spectra``, and ``metadata``.

    Raises
    ------
    ValueError
        If ``spectrum_index`` is outside available rows, or if flattened
        ``DATA_CUBE`` length does not match ``n_lo_pts * n_filters``.
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
    """Return index of the LO frequency sample nearest a target value.

    Parameters
    ----------
    lo_frequencies : ndarray
        One-dimensional LO frequency array in MHz.
    target_freq : float
        Desired frequency in MHz.

    Returns
    -------
    int
        Index of the closest element in ``lo_frequencies``.
    """
    distances = np.abs(lo_frequencies - target_freq)
    return int(np.argmin(distances))
