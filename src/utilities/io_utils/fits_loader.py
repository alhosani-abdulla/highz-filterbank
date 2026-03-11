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
import json
from tqdm import tqdm
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
        logger.debug("Loading calibration for %s...", os.path.basename(cycle_dir))
        
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
        
        # Print calibration info on first load (at DEBUG level)
        # Suppress the .info() output by redirecting to logger
        
        result = {
            'pos': filtercal_pos,
            'neg': filtercal_neg,
            'calibration': filter_cal
        }
        
        # Cache the result
        _calibration_cache[cache_key] = result
        logger.debug("Calibration cached for %s", os.path.basename(cycle_dir))
        
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


class FBFileLoader:
    """Loader for filterbank FITS data with calibration and filter merging.
    
    This loader is designed to handle directories containing cycle subdirectories,
    each with state FITS files and calibration files. It loads, calibrates, and
    merges the 21-filter data into unified spectra suitable for waterfall plotting.
    
    Attributes
    ----------
    dir_path : str
        Path to the day directory containing multiple Cycle_* subdirectories.
    
    Examples
    --------
    >>> loader = FBFileLoader("/path/to/03012026")
    >>> timestamps, frequencies, powers = loader.load(state_no=0)
    """
    
    def __init__(self, dir_path):
        """Initialize loader with day directory path.
        
        Parameters
        ----------
        dir_path : str or Path
            Path to day directory (e.g., "/data/LabTest/03012026").
        """
        self.dir_path = str(dir_path)
        
    @staticmethod
    def get_sorted_cycle_dirs(day_dir):
        """Find and sort all cycle directories in a day folder.
        
        Parameters
        ----------
        day_dir : str or Path
            Path to day directory.
            
        Returns
        -------
        list
            Sorted list of full paths to cycle directories. Returns empty list
            if no cycle directories are found.
            
        Examples
        --------
        >>> get_sorted_cycle_dirs("/data/03012026")
        ['/data/03012026/Cycle_03012026_230', '/data/03012026/Cycle_03012026_231', ...]
        """
        import glob
        
        all_items = glob.glob(os.path.join(day_dir, "*"))
        cycle_dirs = [d for d in all_items if os.path.isdir(d) and 'Cycle_' in os.path.basename(d)]
        cycle_dirs.sort()
        
        logger.info("Found %d cycle directories in %s", len(cycle_dirs), day_dir)
        if len(cycle_dirs) == 0:
            logger.warning("No Cycle_* subdirectories found in %s", day_dir)
            
        return cycle_dirs
    
    @staticmethod
    def _parse_timestamp(timestamp_str, day_str):
        """Parse MMDDYYYY_HHMMSS timestamp from FITS file.
        
        Parameters
        ----------
        timestamp_str : str
            Timestamp string in format "MMDDYYYY_HHMMSS" or "MMDDYYYY_HHMMSS.fits"
            (e.g., "03012026_230530" or "03012026_230530.fits").
        day_str : str
            Day string in format "MMDDYYYY" for validation (e.g., "03012026").
            
        Returns
        -------
        datetime
            Parsed datetime object with UTC timezone.
            
        Notes
        -----
        If the timestamp date doesn't match the day_str (e.g., rollover at midnight),
        the function trusts the timestamp date rather than forcing it to match day_str.
        The instrument C code sometimes appends ".fits" to timestamps, which is
        stripped before parsing.
        """
        from datetime import datetime
        import zoneinfo
        
        # Strip .fits extension if present (from instrument C code)
        if timestamp_str.endswith('.fits'):
            timestamp_str = timestamp_str[:-5]
        
        # Parse MMDDYYYY_HHMMSS format
        try:
            dt = datetime.strptime(timestamp_str, '%m%d%Y_%H%M%S')
            # Add UTC timezone
            utc_tz = zoneinfo.ZoneInfo('UTC')
            return dt.replace(tzinfo=utc_tz)
        except ValueError:
            logger.exception("Failed to parse timestamp: %s", timestamp_str)
            return None
    
    @staticmethod
    def _merge_filters_to_spectrum(frequencies, powers, filter_indices):
        """Merge 21 filter channels into single spectrum, taking minimum at overlaps.
        
        This function combines the frequency-overlapping data from all filter channels
        into a unified spectrum. Where multiple filters observe the same frequency,
        the minimum power value is selected.
        
        Parameters
        ----------
        frequencies : ndarray
            1D array of sky frequencies (MHz) from all filters. Length = n_freq * 21.
        powers : ndarray
            1D array of calibrated power values (dBm). Length = n_freq * 21.
        filter_indices : ndarray
            1D array of filter IDs (0-20). Length = n_freq * 21.
            
        Returns
        -------
        merged_frequencies : ndarray
            Sorted array of unique frequencies.
        merged_powers : ndarray
            Power values at each unique frequency (minimum where overlapping).
            
        Notes
        -----
        The output arrays are sorted by frequency in ascending order.
        """
        # Group powers by frequency (handle floating point comparison with rounding)
        freq_power_map = {}
        
        for freq, power in zip(frequencies, powers):
            # Round frequency to avoid floating point issues (nearest 0.001 MHz)
            freq_key = round(freq, 3)
            
            if freq_key in freq_power_map:
                # Take minimum where frequencies overlap
                freq_power_map[freq_key] = min(freq_power_map[freq_key], power)
            else:
                freq_power_map[freq_key] = power
        
        # Convert to sorted arrays
        sorted_freqs = sorted(freq_power_map.keys())
        merged_frequencies = np.array(sorted_freqs)
        merged_powers = np.array([freq_power_map[f] for f in sorted_freqs])
        
        logger.debug(
            "Merged %d points from 21 filters into %d unique frequency points",
            len(frequencies),
            len(merged_frequencies)
        )
        
        return merged_frequencies, merged_powers
    
    def load(self, 
             state_no, 
             apply_s21=True, 
             apply_alignment=True,
             align_freq_min=50, 
             align_freq_max=80,
             excluded_filters=None,
             s21_dir=DEFAULT_S21_DIR):
        """Load and calibrate all spectra for one state across all cycles in the day.
        
        This method performs the complete data loading pipeline:
        1. Discover all cycle directories in the day folder
        2. Load state FITS files and calibration data for each cycle
        3. Apply S21 corrections (if enabled)
        4. Apply filter alignment normalization (if enabled)
        5. Merge 21 filters into unified spectra (taking minimum at overlaps)
        6. Construct 2D power array (time × frequency)
        
        Parameters
        ----------
        state_no : int
            State number to load (0-7 for typical filterbank states).
        apply_s21 : bool, optional
            If True, apply S21 frequency response corrections. Default is True.
        apply_alignment : bool, optional
            If True, apply inter-filter alignment normalization. Default is True.
        align_freq_min : float, optional
            Lower frequency bound (MHz) for alignment window. Default is 50 MHz.
        align_freq_max : float, optional
            Upper frequency bound (MHz) for alignment window. Default is 80 MHz.
        excluded_filters : list of int, optional
            Filter indices (0-20) to exclude from alignment calculation.
            Default is None (no exclusions).
        s21_dir : str or Path, optional
            Directory containing S21 correction files.
            
        Returns
        -------
        timestamps : ndarray
            1D array of datetime objects with UTC timezone. Shape: (n_spectra,)
        frequencies : ndarray
            1D array of sky frequencies (MHz) after filter merging. Shape: (n_freq,)
        powers : ndarray
            2D array of calibrated power (dBm). Shape: (n_spectra, n_freq).
            Each row corresponds to one spectrum at the corresponding timestamp.
        cycle_ids : ndarray
            1D array of cycle directory basenames. Shape: (n_spectra,)
            
        Examples
        --------
        >>> loader = FBFileLoader("/data/LabTest/03012026")
        >>> timestamps, freqs, powers, cycles = loader.load(state_no=0)
        >>> print(f"Loaded {len(timestamps)} spectra")
        >>> print(f"Frequency range: {freqs.min():.1f} - {freqs.max():.1f} MHz")
        
        Notes
        -----
        - S21 calibration files are loaded once per cycle and cached
        - Memory usage scales with: n_cycles × n_spectra_per_cycle × n_frequencies
        - The frequency array is determined from the first spectrum and assumed
          constant throughout the day
        """
        if excluded_filters is None:
            excluded_filters = []
            
        cycle_dirs = self.get_sorted_cycle_dirs(self.dir_path)
        
        if not cycle_dirs:
            raise ValueError(f"No cycle directories found in {self.dir_path}")
        
        # Extract day string from directory path (e.g., "03012026")
        day_name = os.path.basename(self.dir_path)
        
        # Storage for all loaded spectra
        all_timestamps = []
        all_merged_spectra = []  # List of 1D merged spectra
        all_cycle_ids = []
        reference_frequencies = None  # Will be set from first spectrum
        
        logger.info("Loading state %d from %d cycles...", state_no, len(cycle_dirs))
       
        # Load calibration settings based on toggles
        calib_toggles = []
        if apply_s21:
            calib_toggles.append('s21')
        if apply_alignment:
            calib_toggles.append('alignment') 

        # Process each cycle
        cycle_iterator = tqdm(
            enumerate(cycle_dirs),
            total=len(cycle_dirs),
            desc=f"Loading state {state_no}",
            unit="cycle",
        )
        for cycle_idx, cycle_dir in cycle_iterator:
            cycle_name = os.path.basename(cycle_dir)
            state_file = os.path.join(cycle_dir, f"state_{state_no}.fits")
            
            # Check if state file exists
            if not os.path.exists(state_file):
                logger.warning("State file not found: %s", state_file)
                continue
                
            if os.path.getsize(state_file) == 0:
                logger.warning("Empty state file: %s", state_file)
                continue
                
            filtercal_data = load_calibration_data(cycle_dir, s21_dir, apply_s21)
            filter_cal = filtercal_data.get('calibration') if filtercal_data else None
            
            if not filter_cal and (apply_s21 or apply_alignment):
                logger.warning(
                    "Calibration unavailable for %s, skipping cycle", 
                    cycle_name
                )
                continue
            
            # Load state file to determine number of spectra
            try:
                state_metadata = load_state_file(state_file, spectrum_index=0)
                n_spectra = state_metadata['n_spectra']
                logger.debug("Cycle %s: processing %d spectra", cycle_name, n_spectra)
            except Exception:
                logger.exception("Failed to read state file metadata: %s", state_file)
                continue
            
            # Process each spectrum in this state file
            for spec_idx in range(n_spectra):
                try:
                    # Load one spectrum
                    spectrum_data = load_state_file(state_file, spectrum_index=spec_idx)
                    
                    # Parse timestamp
                    timestamp = self._parse_timestamp(spectrum_data['timestamp'], day_name)
                    if timestamp is None:
                        logger.warning(
                            "Invalid timestamp in %s spectrum %d, skipping",
                            state_file,
                            spec_idx
                        )
                        continue
                    
                    # Apply calibration to get frequencies and powers
                    result = io_utils.apply_calibration_to_spectrum(
                        spectrum_data['data'],
                        spectrum_data['lo_frequencies'],
                        filter_cal if filter_cal else {},
                        return_voltages=False,
                    )
                    frequencies, powers, filter_indices = result
                    
                    # Apply alignment normalization if requested
                    if apply_alignment and filter_cal:
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
                    
                    # Merge 21 filters into single spectrum
                    merged_freq, merged_power = self._merge_filters_to_spectrum(
                        frequencies, powers, filter_indices
                    )
                    
                    # Set reference frequency array from first valid spectrum
                    if reference_frequencies is None:
                        reference_frequencies = merged_freq
                        logger.info(
                            "Reference frequency range: %.2f - %.2f MHz (%d points)",
                            merged_freq.min(),
                            merged_freq.max(),
                            len(merged_freq)
                        )
                    
                    # Verify frequency consistency
                    if not np.array_equal(merged_freq, reference_frequencies):
                        logger.warning(
                            "Frequency mismatch in %s spectrum %d (expected %d points, got %d)",
                            cycle_name,
                            spec_idx,
                            len(reference_frequencies),
                            len(merged_freq)
                        )
                        # Try to interpolate or skip this spectrum
                        # For now, skip spectra with mismatched frequencies
                        continue
                    
                    # Store this spectrum
                    all_timestamps.append(timestamp)
                    all_merged_spectra.append(merged_power)
                    all_cycle_ids.append(cycle_name)
                    
                except Exception:
                    logger.exception(
                        "Failed to process %s spectrum %d",
                        state_file,
                        spec_idx
                    )
                    continue
            
            if (cycle_idx + 1) % 10 == 0:
                logger.info("Processed %d/%d cycles...", cycle_idx + 1, len(cycle_dirs))
        
        # Convert to arrays
        timestamps = np.array(all_timestamps)
        cycle_ids = np.array(all_cycle_ids)
        
        if len(all_merged_spectra) == 0:
            logger.error("No valid spectra loaded!")
            return (np.array([]), np.array([]), 
                    np.empty((0, 0)), np.array([]))
        
        # Stack into 2D array (time × frequency)
        powers_2d = np.vstack(all_merged_spectra)
        
        # Sort by timestamp
        sort_idx = np.argsort(timestamps)
        timestamps = timestamps[sort_idx]
        powers_2d = powers_2d[sort_idx]
        cycle_ids = cycle_ids[sort_idx]
        
        logger.info(
            "Loaded %d spectra. Frequency range: %.2f - %.2f MHz",
            len(timestamps),
            reference_frequencies.min(),
            reference_frequencies.max()
        )
        logger.info(
            "Time range: %s to %s",
            timestamps.min(),
            timestamps.max()
        )
        logger.info(
            "Output shape: timestamps=%s, frequencies=%s, powers=%s",
            timestamps.shape,
            reference_frequencies.shape,
            powers_2d.shape
        )
        
        return timestamps, reference_frequencies, powers_2d, cycle_ids

    def save(self,
             output_path,
             state_no,
             apply_s21=True,
             apply_alignment=True,
             align_freq_min=50,
             align_freq_max=80,
             excluded_filters=None,
             s21_dir=DEFAULT_S21_DIR,
             overwrite=False):
        """Run ``load()`` and save results to a compressed NPZ archive.

        Parameters
        ----------
        output_path : str or Path
            Output archive path. ``.npz`` extension is appended if omitted.
        state_no : int
            State number forwarded to ``load()``.
        excluded_filters : list[int] or None, optional
            Filter indices excluded from alignment calculation.
        s21_dir : str or Path, optional
            Directory containing S21 correction files.
        overwrite : bool, optional
            If False and output already exists, raises ``FileExistsError``.

        Returns
        -------
        Path
            Path to the written ``.npz`` file.

        Notes
        -----
        A sidecar JSON file named ``<output_stem>_metadata.json`` is also
        written with load settings and output summary.
        """
        if excluded_filters is None:
            excluded_filters = []

        output_path = Path(output_path)
        if output_path.suffix.lower() != ".npz":
            output_path = output_path.with_suffix(".npz")

        if output_path.exists() and not overwrite:
            raise FileExistsError(
                f"Output file already exists: {output_path}. "
                "Use overwrite=True to replace it."
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)

        timestamps, frequencies, powers, cycle_ids = self.load(
            state_no=state_no,
            apply_s21=apply_s21,
            apply_alignment=apply_alignment,
            align_freq_min=align_freq_min,
            align_freq_max=align_freq_max,
            excluded_filters=excluded_filters,
            s21_dir=s21_dir,
        )

        timestamps_iso = np.array(
            [ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
             for ts in timestamps],
            dtype="U32",
        )

        np.savez_compressed(
            output_path,
            timestamps=timestamps_iso,
            frequencies=frequencies,
            powers=powers,
            cycle_ids=cycle_ids,
        )

        metadata = {
            "source_dir": self.dir_path,
            "state_no": int(state_no),
            "apply_s21": bool(apply_s21),
            "apply_alignment": bool(apply_alignment),
            "align_freq_min": float(align_freq_min),
            "align_freq_max": float(align_freq_max),
            "excluded_filters": [int(x) for x in excluded_filters],
            "s21_dir": str(s21_dir) if s21_dir is not None else None,
            "n_spectra": int(powers.shape[0]) if powers.ndim >= 1 else 0,
            "n_freq": int(frequencies.shape[0]) if frequencies.ndim >= 1 else 0,
            "npz_file": output_path.name,
        }

        metadata_path = output_path.with_name(f"{output_path.stem}_metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        logger.info("Saved load() results to %s", output_path)
        logger.info("Saved metadata to %s", metadata_path)

        return output_path
    
