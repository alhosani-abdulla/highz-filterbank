#!/usr/bin/env python3
"""
Waterfall Plotter for Consolidated Filterbank Data

Creates spectrogram/waterfall plots from consolidated FITS files.
Shows power vs time and RF frequency for selected states.

The script reconstructs RF frequencies from the data cubes using the same
approach as historical_viewer.py:
    RF_frequency = (2.6 * filter_index + 904) - LO_frequency

Usage:
    python waterfall_plotter.py /path/to/20251106 --state 1
    python waterfall_plotter.py /path/to/20251106 --state 1 2 3
    python waterfall_plotter.py /path/to/20251106 --all-states
    python waterfall_plotter.py /path/to/20251106 --state 1 --freq-range 50 200
"""

import argparse
import numpy as np
from astropy.io import fits
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.widgets import RectangleSelector
from datetime import datetime
import json
from typing import List, Tuple, Optional
import sys

# Add parent paths to import calibration utilities
root_dir = Path(__file__).parent.parent.parent  # src/filterbank/visualization -> src
highz_filterbank_root = root_dir.parent.parent  # src -> Highz-EXP
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(highz_filterbank_root / "highz-filterbank" / "tools" / "rtviewer"))

try:
    import calibration_utils as cal
    CAL_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import calibration_utils: {e}")
    print("Will use fallback ADC conversion")
    CAL_AVAILABLE = False
    cal = None

# Configuration
S21_DIR = highz_filterbank_root / "highz-filterbank" / "characterization" / "s_parameters"
APPLY_S21_CORRECTIONS = True  # Re-enable with correct scikit-rf loading
APPLY_FILTER_NORMALIZATION = True


def load_s2p_file(filename: Path):
    """
    Load S2P (Touchstone) file and extract S21 magnitude in dB.
    Uses scikit-rf to properly handle rectangular (real/imaginary) format.
    """
    try:
        import skrf as rf
        
        # Load the network from S2P file
        network = rf.Network(str(filename))
        
        # Get frequency in MHz
        freqs_mhz = network.frequency.f / 1e6
        
        # Extract S21 (parameter [1,0] in S-parameter matrix)
        # S21 is the forward transmission coefficient
        s21_complex = network.s[:, 1, 0]  # s[freq_index, port_out, port_in]
        
        # Convert complex S21 to magnitude in dB: 20*log10(|S21|)
        s21_mag = np.abs(s21_complex)
        s21_db = 20 * np.log10(s21_mag + 1e-12)  # Add small value to avoid log(0)
        
        return np.array(freqs_mhz), np.array(s21_db)
    except Exception as e:
        return None, None


def load_s21_corrections(s21_dir: Path = None) -> dict:
    """Load S21 correction data for all filters."""
    if s21_dir is None:
        s21_dir = S21_DIR
    
    if not s21_dir.exists():
        return None
    
    s21_data = {}
    for filt_num in range(21):
        s2p_file = s21_dir / f"filter_{filt_num:02d}.s2p"
        if not s2p_file.exists():
            continue
        
        freqs, s21_db = load_s2p_file(s2p_file)
        if freqs is not None:
            s21_data[filt_num] = {
                'freqs': freqs,
                's21_db': s21_db
            }
    
    return s21_data if len(s21_data) > 0 else None


def makeSingleListOfInts(a1, a2, a3):
    """Convert three ADC arrays to single list of integers."""
    ADC1, ADC2, ADC3 = list(), list(), list()
    for i in range(len(a1)):
        ADC1.append(int(a1[i]))
        ADC2.append(int(a2[i]))
        ADC3.append(int(a3[i]))
    return ADC1 + ADC2 + ADC3


def toVolts(data):
    """Convert ADC counts to voltage."""
    adjustedData = []
    REF = 5.0
    for i in data:
        if (i >> 31) == 1:
            divisor = 2**31
            adjustedData.append(REF * 2 - i/divisor * REF)
        else:
            divisor = 2**31 - 1
            adjustedData.append(i/divisor * REF)
    return adjustedData


def check_spectrum_quality(rf_freqs: np.ndarray, powers: np.ndarray) -> bool:
    """
    Check if a spectrum appears to be shifted due to LO/ADC sync issues.
    
    Returns True if spectrum is GOOD, False if suspect.
    """
    # Sort by RF frequency
    sort_idx = np.argsort(rf_freqs)
    power_sorted = powers[sort_idx]
    
    n_points = len(power_sorted)
    if n_points < 20:
        return True  # Not enough data to judge, assume good
    
    # Analyze first third of spectrum
    first_third_size = max(15, int(n_points * 0.33))
    first_third_power = power_sorted[:first_third_size]
    rest_power = power_sorted[first_third_size:]
    
    first_third_mean = np.mean(first_third_power)
    first_third_std = np.std(first_third_power)
    rest_mean = np.mean(rest_power)
    
    # Detect noise floor: flat, low power, significantly different from rest
    is_flat_noise = first_third_std < 3.0
    is_low_power = first_third_mean < -45.0
    is_different_from_rest = (rest_mean - first_third_mean) > 5.0
    
    # Spectrum is suspect if it has noise floor at start
    is_suspect = is_flat_noise and is_low_power and is_different_from_rest
    
    return not is_suspect  # Return True for good, False for suspect


def load_filter_calibration(cycle_dir: Path = None, calib_dir: Path = None, verbose: bool = False) -> dict:
    """
    Load filter calibration data from 0dBm and -9dBm calibration files.
    Uses filter-center LO frequencies for calibration.
    Applies S21 corrections if available.
    
    Args:
        cycle_dir: Cycle directory containing filtercal files (preferred)
        calib_dir: Fallback calibration directory
        verbose: Print detailed information
    
    Returns dictionary with filter number as key and calibration parameters:
    {'slope': float, 'intercept': float, 's21_db': float}
    """
    filter_cal = {}
    
    # Try cycle directory first, then fallback to calib_dir
    search_dir = cycle_dir if cycle_dir and cycle_dir.exists() else calib_dir
    
    if not search_dir or not search_dir.exists():
        if verbose:
            print("Warning: No calibration directory found, using fallback calibration")
        return filter_cal
    
    try:
        # Find calibration files
        high_files = sorted(list(search_dir.glob('*+5dBm.fits')) + 
                           list(search_dir.glob('*0dBm.fits')) +
                           list(search_dir.glob('filtercal_+5dBm.fits')))
        low_files = sorted(list(search_dir.glob('*-4dBm.fits')) + 
                          list(search_dir.glob('*-9dBm.fits')) +
                          list(search_dir.glob('filtercal_-4dBm.fits')))
        
        if not high_files or not low_files:
            if verbose:
                print(f"Warning: Could not find both calibration files in {search_dir}")
            return filter_cal
        
        # Use most recent files
        high_file = high_files[-1]
        low_file = low_files[-1]
        
        if verbose:
            print(f"Loading calibration: {high_file.name}, {low_file.name}")
        
        # Actual power levels at LO output
        low_power_dbm = -9.0
        high_power_dbm = 0.0
        
        # Load S21 corrections if enabled
        s21_corrections = None
        if APPLY_S21_CORRECTIONS:
            s21_corrections = load_s21_corrections()
            if s21_corrections and verbose:
                print(f"Loaded S21 corrections for {len(s21_corrections)} filters")
        
        # Filter center frequencies
        filter_centers = [904.0 + i * 2.6 for i in range(21)]
        
        # Load calibration data
        with fits.open(low_file) as hdul:
            low_data = hdul[1].data
            n_lo_pts_low = hdul[0].header.get('N_LO_PTS', 301)
        
        with fits.open(high_file) as hdul:
            high_data = hdul[1].data
            n_lo_pts_high = hdul[0].header.get('N_LO_PTS', 301)
        
        # Reconstruct LO frequencies for filter calibrations
        # Filter cals sweep 900-960 MHz in 0.2 MHz steps (301 points)
        lo_frequencies = get_lo_frequencies(n_lo_pts_low)
        
        # Convert DATA_CUBE to voltages at each LO frequency
        # Low power calibration
        low_data_cube = low_data[0]['DATA_CUBE']
        low_cube_2d = low_data_cube.reshape(21, n_lo_pts_low)
        
        # High power calibration
        high_data_cube = high_data[0]['DATA_CUBE']
        high_cube_2d = high_data_cube.reshape(21, n_lo_pts_high)
        
        # For each filter, find LO frequency closest to filter center
        for filt_num in range(21):
            center_freq = filter_centers[filt_num]
            
            # Find LO frequency closest to this filter's center
            lo_diffs = np.abs(lo_frequencies - center_freq)
            closest_lo_idx = np.argmin(lo_diffs)
            
            # Only use if within 1 MHz
            if lo_diffs[closest_lo_idx] > 1.0:
                continue
            
            # Get ADC counts at this LO for all filters, then convert to voltage
            low_adc = low_cube_2d[:, closest_lo_idx]
            if CAL_AVAILABLE and cal:
                low_volts = cal.toVolts(low_adc.astype(int).tolist())
            else:
                low_volts = toVolts(low_adc.astype(int).tolist())
            low_voltage = low_volts[filt_num]
            
            high_adc = high_cube_2d[:, closest_lo_idx]
            if CAL_AVAILABLE and cal:
                high_volts = cal.toVolts(high_adc.astype(int).tolist())
            else:
                high_volts = toVolts(high_adc.astype(int).tolist())
            high_voltage = high_volts[filt_num]
            
            # Apply S21 correction if available
            s21_loss_db = 0.0
            if s21_corrections and filt_num in s21_corrections:
                s21_freqs = s21_corrections[filt_num]['freqs']
                s21_db = s21_corrections[filt_num]['s21_db']
                s21_loss_db = np.interp(center_freq, s21_freqs, s21_db)
            
            # Adjust power levels for S21 loss
            low_power_at_detector = low_power_dbm + s21_loss_db
            high_power_at_detector = high_power_dbm + s21_loss_db
            
            # Calculate calibration curve
            voltage_diff = high_voltage - low_voltage
            if abs(voltage_diff) < 0.001:
                continue
            
            slope = (high_power_at_detector - low_power_at_detector) / voltage_diff
            intercept = low_power_at_detector - slope * low_voltage
            
            filter_cal[filt_num] = {
                'slope': slope,
                'intercept': intercept,
                'low_v': low_voltage,
                'high_v': high_voltage,
                's21_db': s21_loss_db
            }
        
        if verbose:
            print(f"Loaded calibration for {len(filter_cal)} filters")
        
    except Exception as e:
        if verbose:
            print(f"Error loading calibration: {e}")
            import traceback
            traceback.print_exc()
    
    return filter_cal


def calculate_filter_normalization(waterfall: 'WaterfallData', 
                                   freq_min: float = 50, 
                                   freq_max: float = 80,
                                   excluded_filters: list = [0, 1, 13, 16, 20]) -> dict:
    """
    Calculate normalization factors to align filter responses.
    
    Uses mean power in a reference frequency region (50-80 MHz) to calculate
    per-filter offsets that bring all filters to the same level.
    """
    if not APPLY_FILTER_NORMALIZATION:
        return None
    
    # Organize data by filter
    filter_data = {}
    for i in range(len(waterfall.timestamps)):
        rf_freqs = waterfall.rf_frequencies[i]
        powers = waterfall.powers[i]
        filters = waterfall.filter_indices[i]
        
        for freq, power, filt in zip(rf_freqs, powers, filters):
            if filt not in filter_data:
                filter_data[filt] = {'freqs': [], 'powers': []}
            filter_data[filt]['freqs'].append(freq)
            filter_data[filt]['powers'].append(power)
    
    # Get valid filters
    valid_filters = [f for f in filter_data.keys() 
                    if f not in excluded_filters and len(filter_data[f]['freqs']) > 1]
    
    if len(valid_filters) < 2:
        return None
    
    # Calculate mean power in reference region for each filter
    region_data = {}
    for filt in valid_filters:
        freqs = np.array(filter_data[filt]['freqs'])
        powers = np.array(filter_data[filt]['powers'])
        
        mask = (freqs >= freq_min) & (freqs <= freq_max)
        region_powers = powers[mask]
        
        if len(region_powers) > 0:
            region_data[filt] = np.mean(region_powers)
    
    if len(region_data) < 2:
        return None
    
    # Calculate global mean
    mean_region_power = np.mean(list(region_data.values()))
    
    # Calculate per-filter offset
    normalization = {}
    for filt in region_data:
        offset = mean_region_power - region_data[filt]
        normalization[filt] = offset
    
    return normalization


class WaterfallData:
    """Container for waterfall plot data."""
    
    def __init__(self, state: str):
        self.state = state
        self.timestamps = []
        self.rf_frequencies = []  # Will be a 2D array: (n_spectra, n_rf_points)
        self.powers = []  # Will be a 2D array: (n_spectra, n_rf_points)
        self.filter_indices = []  # Which filter each RF point came from
        
    def add_spectrum(self, timestamp: str, rf_freqs: np.ndarray, power_values: np.ndarray, filter_nums: np.ndarray):
        """Add a spectrum to the waterfall data."""
        self.timestamps.append(timestamp)
        self.rf_frequencies.append(rf_freqs)
        self.powers.append(power_values)
        self.filter_indices.append(filter_nums)
        
    def to_arrays(self):
        """Convert lists to numpy arrays for plotting."""
        self.rf_frequencies = np.array(self.rf_frequencies)
        self.powers = np.array(self.powers)
        self.filter_indices = np.array(self.filter_indices)
        return self


def get_lo_frequencies(n_lo_pts: int) -> np.ndarray:
    """
    Reconstruct the LO frequency sweep.
    
    Regular spectra: 650-934 MHz in 2 MHz steps (144 points)
    Filter calibrations: 900-960 MHz in 0.2 MHz steps (301 points)
    """
    if n_lo_pts == 144:
        # Regular spectrum
        return np.arange(650, 935, 2)
    elif n_lo_pts == 301:
        # Filter calibration
        return np.arange(900, 960.1, 0.2)
    else:
        raise ValueError(f"Unexpected N_LO_PTS: {n_lo_pts}. Expected 144 or 301.")


def calculate_rf_frequencies(lo_freq: float, n_filters: int = 21) -> np.ndarray:
    """
    Calculate RF frequencies for all filters at a given LO frequency.
    
    Formula: RF = (2.6 * filter_index + 904) - LO
    
    Args:
        lo_freq: LO frequency in MHz
        n_filters: Number of filters (default 21)
        
    Returns:
        Array of RF frequencies for each filter
    """
    filter_indices = np.arange(n_filters)
    return (2.6 * filter_indices + 904) - lo_freq


def _check_spectrum_quality(rf_freqs: np.ndarray, powers: np.ndarray) -> dict:
    """
    Check if a spectrum appears to be shifted due to LO/ADC sync issues.
    
    The issue: ADC starts collecting before LO sweep starts, so the
    beginning shows flat noise floor around -60 dBm for ~first third of spectrum.
    
    Detection: Look for flat, low-power region at the beginning.
    
    Returns dict with:
        - is_suspect: bool - True if spectrum appears problematic
        - reasons: list[str] - List of reasons why spectrum is suspect
        - metrics: dict - Statistics about spectrum quality
    """
    reasons = []
    
    # Sort by RF frequency to analyze spectrum from low to high freq
    sort_idx = np.argsort(rf_freqs)
    rf_sorted = rf_freqs[sort_idx]
    power_sorted = powers[sort_idx]
    
    n_points = len(power_sorted)
    if n_points < 20:  # Need enough points to analyze
        return {'is_suspect': False, 'reasons': [], 'metrics': {}}
    
    # Analyze first third of spectrum (where noise floor appears in bad spectra)
    first_third_size = max(15, int(n_points * 0.33))
    
    first_third_power = power_sorted[:first_third_size]
    rest_power = power_sorted[first_third_size:]
    
    # Calculate statistics
    first_third_mean = np.mean(first_third_power)
    first_third_std = np.std(first_third_power)
    rest_mean = np.mean(rest_power)
    rest_std = np.std(rest_power)
    
    metrics = {
        'begin_mean': first_third_mean,
        'begin_std': first_third_std,
        'middle_mean': rest_mean,
        'middle_std': rest_std,
    }
    
    # Detection: First third is FLAT (low std) AND low power (around -60 dBm or below -50)
    # AND significantly different from rest of spectrum
    
    is_flat_noise = first_third_std < 3.0  # Low variation (< 3 dB std)
    is_low_power = first_third_mean < -45.0  # Lower threshold to catch more cases
    is_different_from_rest = (rest_mean - first_third_mean) > 5.0  # At least 5 dB difference
    
    if is_flat_noise and is_low_power and is_different_from_rest:
        reasons.append(f'Noise floor at start: {first_third_mean:.1f} dBm (σ={first_third_std:.2f}), '
                      f'{rest_mean - first_third_mean:.1f} dB below rest')
    
    return {
        'is_suspect': len(reasons) > 0,
        'reasons': reasons,
        'metrics': metrics
    }


def _compare_to_reference(rf_freqs: np.ndarray, powers: np.ndarray,
                         ref_rf_freqs: np.ndarray, ref_powers: np.ndarray) -> dict:
    """
    Compare a spectrum to a reference (known-good) spectrum.
    
    Returns dict with:
        - is_suspect: bool - True if too different from reference
        - reasons: list[str] - Why it's suspect
        - metrics: dict - Comparison metrics
    """
    from scipy.interpolate import interp1d
    
    reasons = []
    
    # Sort both spectra by RF frequency
    sort_idx = np.argsort(rf_freqs)
    rf_sorted = rf_freqs[sort_idx]
    power_sorted = powers[sort_idx]
    
    ref_sort_idx = np.argsort(ref_rf_freqs)
    ref_rf_sorted = ref_rf_freqs[ref_sort_idx]
    ref_power_sorted = ref_powers[ref_sort_idx]
    
    # Interpolate test spectrum onto reference frequency grid
    try:
        interp_func = interp1d(rf_sorted, power_sorted, 
                              kind='linear', bounds_error=False, fill_value=np.nan)
        power_interp = interp_func(ref_rf_sorted)
        
        # Calculate metrics where both have valid data
        valid_mask = ~np.isnan(power_interp)
        if np.sum(valid_mask) < 10:
            return {'is_suspect': False, 'reasons': ['Not enough overlap'], 'metrics': {}}
        
        # Calculate difference
        diff = power_interp[valid_mask] - ref_power_sorted[valid_mask]
        
        mean_diff = np.mean(diff)
        std_diff = np.std(diff)
        max_diff = np.max(np.abs(diff))
        
        # Calculate correlation
        correlation = np.corrcoef(power_interp[valid_mask], ref_power_sorted[valid_mask])[0, 1]
        
        metrics = {
            'mean_diff': mean_diff,
            'std_diff': std_diff,
            'max_diff': max_diff,
            'correlation': correlation,
            'overlap_points': np.sum(valid_mask)
        }
        
        # Detection criteria
        # 1. Large systematic offset (more than 5.5 dB difference on average)
        if abs(mean_diff) > 5.5:
            reasons.append(f'Large offset from reference (mean Δ={mean_diff:.1f} dB)')
        
        # 2. High variability in difference (spectra have different shape)
        if std_diff > 2.8:
            reasons.append(f'Different shape from reference (σ={std_diff:.1f} dB)')
        
        # 3. Poor correlation (< 0.82 means very different pattern)
        if correlation < 0.82:
            reasons.append(f'Low correlation with reference (r={correlation:.3f})')
        
        return {
            'is_suspect': len(reasons) > 0,
            'reasons': reasons,
            'metrics': metrics
        }
        
    except Exception as e:
        return {'is_suspect': False, 'reasons': [f'Comparison failed: {e}'], 'metrics': {}}


def load_state_file(fits_path: Path, 
                    cycle_dir: Path = None,
                    filter_cal: dict = None,
                    filter_num: Optional[int] = None,
                    reference_spectrum: Optional[str] = None,
                    verbose: bool = False) -> Tuple[WaterfallData, dict]:
    """
    Load a consolidated state FITS file and extract waterfall data.
    
    Args:
        fits_path: Path to the state FITS file
        cycle_dir: Cycle directory (for loading calibration files)
        filter_cal: Filter calibration dictionary (optional, will load from cycle_dir if None)
        filter_num: Optional - process only this filter number (0-20)
        reference_spectrum: Optional reference for quality comparison. Format "cycle_name:index"
        verbose: Print detailed information
        
    Returns:
        Tuple of (WaterfallData, metadata_dict)
    """
    if verbose:
        print(f"\nLoading: {fits_path.name}")
    
    # Load filter calibration from cycle directory if not provided
    if filter_cal is None and cycle_dir:
        filter_cal = load_filter_calibration(cycle_dir=cycle_dir, verbose=verbose)
    
    with fits.open(fits_path) as hdul:
        # Read header metadata
        header = hdul[0].header
        state = str(header.get('STATE', 'unknown'))
        n_filters = header.get('N_FILTERS', 21)
        n_lo_pts = header.get('N_LO_PTS', 144)
        
        metadata = {
            'cycle_id': header.get('CYCLE_ID', 'unknown'),
            'state': state,
            'n_filters': n_filters,
            'n_lo_pts': n_lo_pts,
            'antenna': header.get('ANTENNA', 'unknown')
        }
        
        # Read binary table data
        data = hdul[1].data
        
        if verbose:
            print(f"  State: {state}")
            print(f"  Spectra: {len(data)}")
            print(f"  Filters: {n_filters}, LO points: {n_lo_pts}")
        
        # Reconstruct LO frequencies
        lo_frequencies = get_lo_frequencies(n_lo_pts)
        
        # Initialize waterfall data container
        waterfall = WaterfallData(state)
        
        # Load reference spectrum if provided (for relative comparison quality checks)
        reference_rf_freqs = None
        reference_powers = None
        
        if reference_spectrum and filter_num is not None:
            try:
                parts = reference_spectrum.split(':')
                if len(parts) == 2:
                    cycle_pattern, idx_str = parts
                    spectrum_idx = int(idx_str)
                    
                    # Find the reference spectrum in the day directory
                    if cycle_dir and cycle_dir.parent:
                        day_dir = cycle_dir.parent
                        matching_cycles = [d for d in sorted(day_dir.iterdir()) 
                                         if d.is_dir() and d.name.startswith('cycle_') and cycle_pattern in d.name]
                        
                        if matching_cycles:
                            ref_cycle_dir = matching_cycles[0]
                            ref_state = state  # Use same state for reference
                            ref_state_file = ref_cycle_dir / f"state_{ref_state}.fits"
                            if not ref_state_file.exists():
                                ref_state_file = ref_cycle_dir / f"state_{ref_state}_OC.fits"
                            
                            if ref_state_file.exists():
                                # Load reference spectrum recursively (without reference to avoid infinite loop)
                                ref_waterfall, _ = load_state_file(
                                    ref_state_file, 
                                    cycle_dir=ref_cycle_dir,
                                    filter_cal=filter_cal,
                                    filter_num=filter_num,
                                    reference_spectrum=None,  # Don't recurse
                                    verbose=False
                                )
                                
                                if spectrum_idx < len(ref_waterfall.timestamps):
                                    reference_rf_freqs = ref_waterfall.rf_frequencies[spectrum_idx]
                                    reference_powers = ref_waterfall.powers[spectrum_idx]
                                    
                                    if verbose:
                                        print(f"  Loaded reference spectrum from {ref_cycle_dir.name}:{spectrum_idx}")
                                        print(f"    Mean power: {np.mean(reference_powers):.1f} dBm")
                                else:
                                    if verbose:
                                        print(f"  Warning: Reference spectrum index {spectrum_idx} out of range")
            except Exception as e:
                if verbose:
                    print(f"  Warning: Could not load reference spectrum: {e}")
        
        # Determine if this is a calibration state (apply quality checks)
        # Calibration states: 2, 3, 4, 5, 6, 7, 1_OC, 0
        # State 1 is NOT a calibration state (skip quality checks - no filtering)
        is_calibration_state = state not in ['1']
        
        # Step 1: Apply position-based exclusions (hard cutoffs)
        # State 1: Exclude first AND last (has many spectra, boundary issues)
        # Other states with >2 spectra: Exclude only last (LO/ADC sync at end)
        # States with <=2 spectra: Keep all
        position_excluded = set()
        
        if state == '1':
            if len(data) > 2:
                position_excluded = set(list(range(1)) + list(range(len(data) - 1, len(data))))  # First and last
                if verbose:
                    print(f"  State 1: Position-based exclusion of first and last (indices 0, {len(data)-1})")
            else:
                if verbose:
                    print(f"  Warning: State 1 only has {len(data)} spectra, not excluding any by position")
        else:
            # All other states: exclude only last if more than 2 spectra
            if len(data) > 2:
                position_excluded = {len(data) - 1}  # Last spectrum
                if verbose:
                    print(f"  Position-based exclusion of last spectrum (index {len(data)-1})")
            else:
                if verbose:
                    print(f"  Only {len(data)} spectra, not excluding any by position")
        
        # Step 2: Process all spectra and apply quality checks to remaining ones
        all_spectra_rf = []
        all_spectra_power = []
        quality_excluded = set()
        
        if verbose and is_calibration_state:
            print(f"  Will perform quality checks on non-excluded spectra (calibration state)...")
        elif verbose:
            print(f"  Skipping quality checks (state 1)...")
        
        # Process each spectrum
        for spectrum_idx, row in enumerate(data):
            timestamp = row['SPECTRUM_TIMESTAMP']
            data_cube = row['DATA_CUBE']
            
            # Get actual LO frequencies if available (handles circular bug)
            if 'LO_FREQUENCIES' in data.dtype.names:
                actual_lo_freqs = row['LO_FREQUENCIES']
            else:
                # Fallback: use reconstructed LO frequencies
                actual_lo_freqs = lo_frequencies
            
            # Reshape data cube to (n_filters, n_lo_pts)
            cube_2d = data_cube.reshape(n_filters, n_lo_pts)
            
            # For single filter mode: use actual LO frequencies to calculate RF
            # For multi-filter mode: calculate RF frequencies for all filters
            if filter_num is not None:
                # Single filter: store power and actual RF frequencies
                all_powers = []
                all_rf_freqs = []
                
                filter_center = 904 + 2.6 * filter_num
                
                for lo_idx in range(n_lo_pts):
                    adc_count = cube_2d[filter_num, lo_idx]
                    lo_freq = actual_lo_freqs[lo_idx]
                    
                    # Convert to voltage
                    if CAL_AVAILABLE and cal:
                        voltage = cal.toVolts([int(adc_count)])[0]
                    else:
                        voltage = toVolts([int(adc_count)])[0]
                    
                    # Convert to power
                    if filter_cal and filter_num in filter_cal:
                        slope = filter_cal[filter_num]['slope']
                        intercept = filter_cal[filter_num]['intercept']
                        power = slope * voltage + intercept
                    else:
                        power = -43.5 * voltage + 24.98
                    
                    # Calculate actual RF frequency from actual LO
                    rf_freq = filter_center - lo_freq
                    
                    all_powers.append(power)
                    all_rf_freqs.append(rf_freq)
                
                all_rf_freqs = np.array(all_rf_freqs)
                all_powers = np.array(all_powers)
                all_filter_nums = np.full(n_lo_pts, filter_num)
            else:
                # Multi-filter mode: calculate RF frequencies for all filters
                all_rf_freqs = []
                all_powers = []
                all_filter_nums = []
                
                for lo_idx, lo_freq in enumerate(lo_frequencies):
                    adc_counts_at_lo = cube_2d[:, lo_idx]
                    
                    if CAL_AVAILABLE and cal:
                        volts_at_lo = cal.toVolts(adc_counts_at_lo.astype(int).tolist())
                    else:
                        volts_at_lo = toVolts(adc_counts_at_lo.astype(int).tolist())
                    
                    for filt_num in range(n_filters):
                        voltage = volts_at_lo[filt_num]
                        
                        if filter_cal and filt_num in filter_cal:
                            slope = filter_cal[filt_num]['slope']
                            intercept = filter_cal[filt_num]['intercept']
                            power = slope * voltage + intercept
                        else:
                            power = -43.5 * voltage + 24.98
                        
                        rf_freq = (2.6 * filt_num + 904) - lo_freq
                        
                        all_rf_freqs.append(rf_freq)
                        all_powers.append(power)
                        all_filter_nums.append(filt_num)
            
            # Store for quality checking
            all_spectra_rf.append(np.array(all_rf_freqs))
            all_spectra_power.append(np.array(all_powers))
            
            # Check spectrum quality for calibration states (but only if not position-excluded)
            if is_calibration_state and spectrum_idx not in position_excluded and filter_num is not None:
                # Use relative comparison if reference is available, otherwise skip
                if reference_rf_freqs is not None:
                    quality = _compare_to_reference(all_rf_freqs, all_powers, 
                                                   reference_rf_freqs, reference_powers)
                    if quality['is_suspect']:
                        quality_excluded.add(spectrum_idx)
                # For calibration states without reference, don't apply quality checks
        
        # Step 3: Add spectra to waterfall, excluding both position-excluded and quality-excluded
        for spectrum_idx, (all_rf_freqs, all_powers) in enumerate(zip(all_spectra_rf, all_spectra_power)):
            # Skip position-excluded spectra
            if spectrum_idx in position_excluded:
                if verbose:
                    print(f"  Excluding spectrum {spectrum_idx} ({data[spectrum_idx]['SPECTRUM_TIMESTAMP']}) - position-based cutoff")
                continue
            
            # Skip quality-excluded spectra
            if spectrum_idx in quality_excluded:
                if verbose:
                    print(f"  Excluding spectrum {spectrum_idx} ({data[spectrum_idx]['SPECTRUM_TIMESTAMP']}) - quality check failed")
                continue
            
            # Get filter numbers for this spectrum
            if filter_num is not None:
                all_filter_nums = np.full(len(all_rf_freqs), filter_num)
            else:
                # Multi-filter mode needs filter nums reconstruction
                all_filter_nums = []
                n_lo = len([x for x in all_spectra_power[spectrum_idx] if x is not None]) // n_filters if n_filters > 0 else 1
                for _ in range(n_lo):
                    for filt_num in range(n_filters):
                        all_filter_nums.append(filt_num)
                all_filter_nums = np.array(all_filter_nums)
            
            # Add spectrum to waterfall
            waterfall.add_spectrum(
                data[spectrum_idx]['SPECTRUM_TIMESTAMP'],
                all_rf_freqs,
                all_powers,
                all_filter_nums
            )
        
        # Convert to arrays
        waterfall.to_arrays()
        
        # Print summary
        if verbose:
            total_spectra = len(data)
            excluded_by_position = len(position_excluded)
            excluded_by_quality = len(quality_excluded)
            included_count = total_spectra - excluded_by_position - excluded_by_quality
            
            summary = f"  Processing summary: {included_count}/{total_spectra} spectra included"
            if excluded_by_position > 0:
                summary += f" (excluded {excluded_by_position} by position"
            if excluded_by_quality > 0:
                if excluded_by_position > 0:
                    summary += f", {excluded_by_quality} by quality)"
                else:
                    summary += f" (excluded {excluded_by_quality} by quality)"
            elif excluded_by_position > 0:
                summary += ")"
            print(summary)
            
            # Indicate quality check status
            if is_calibration_state:
                if reference_rf_freqs is not None:
                    print(f"  Quality checks: ENABLED (using relative comparison to reference)")
                else:
                    print(f"  Quality checks: DISABLED (no reference spectrum provided)")
            else:
                print(f"  Quality checks: DISABLED (state 1 is non-calibration)")
        
        if verbose:
            if len(waterfall.timestamps) > 0:
                print(f"  RF frequency range: {waterfall.rf_frequencies.min():.1f} - {waterfall.rf_frequencies.max():.1f} MHz")
                print(f"  Power range: {waterfall.powers.min():.1f} - {waterfall.powers.max():.1f} dBm")
        
        return waterfall, metadata


def create_waterfall_grid(waterfall: WaterfallData, 
                          freq_bins: Optional[np.ndarray] = None,
                          freq_range: Optional[Tuple[float, float]] = None,
                          filter_num: Optional[int] = None) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Create a regular 2D grid for waterfall plotting.
    
    For single-filter mode: RF frequencies are actually LO indices (0-143), 
    which we convert to a regular grid directly without interpolation.
    
    For multi-filter mode: Interpolate irregular RF frequencies onto regular grid.
    
    Args:
        waterfall: WaterfallData object
        freq_bins: Custom frequency bin edges (optional)
        freq_range: (min_freq, max_freq) to limit plotting range
        filter_num: If set, indicates single-filter mode (RF freqs are LO indices)
        
    Returns:
        Tuple of (time_array, freq_centers, power_grid)
        where power_grid has shape (n_times, n_freq_bins)
    """
    from scipy.interpolate import interp1d
    
    n_spectra = len(waterfall.timestamps)
    
    if filter_num is not None:
        # Single filter mode: RF frequencies are actual values from LO sweep
        # Need to sort and interpolate onto regular grid since circular bug causes different RF ranges
        
        # Determine frequency range
        if freq_range:
            freq_min, freq_max = freq_range
        else:
            freq_min = waterfall.rf_frequencies.min()
            freq_max = waterfall.rf_frequencies.max()
        
        # Create regular frequency grid (1 MHz spacing)
        freq_centers = np.arange(freq_min, freq_max + 1, 1.0)
        n_freq_bins = len(freq_centers)
        
        # Initialize power grid
        power_grid = np.zeros((n_spectra, n_freq_bins))
        
        # Interpolate each spectrum onto the regular frequency grid
        from scipy.interpolate import interp1d
        
        for i in range(n_spectra):
            rf_freqs = waterfall.rf_frequencies[i]
            powers = waterfall.powers[i]
            
            # Sort by frequency (required for interpolation)
            sort_idx = np.argsort(rf_freqs)
            rf_freqs_sorted = rf_freqs[sort_idx]
            powers_sorted = powers[sort_idx]
            
            # Remove duplicate frequencies (circular buffer bug causes this)
            # Keep first occurrence of each unique frequency
            unique_mask = np.concatenate(([True], np.diff(rf_freqs_sorted) > 1e-6))
            rf_freqs_unique = rf_freqs_sorted[unique_mask]
            powers_unique = powers_sorted[unique_mask]
            
            # Interpolate onto regular grid
            try:
                interp_func = interp1d(rf_freqs_unique, powers_unique, 
                                      kind='linear', 
                                      bounds_error=False, 
                                      fill_value=np.nan)
                power_grid[i, :] = interp_func(freq_centers)
            except Exception as e:
                # If interpolation fails, fill with NaN
                power_grid[i, :] = np.nan
        
        time_array = np.arange(n_spectra)
        
        return time_array, freq_centers, power_grid
    
    else:
        # Multi-filter mode: use interpolation as before
        # Determine frequency range
        if freq_range:
            freq_min, freq_max = freq_range
        else:
            freq_min = waterfall.rf_frequencies.min()
            freq_max = waterfall.rf_frequencies.max()
        
        # Create frequency grid if not provided
        if freq_bins is None:
            # Use 1 MHz spacing for final grid
            freq_centers = np.arange(freq_min, freq_max + 1, 1.0)
        else:
            freq_centers = (freq_bins[:-1] + freq_bins[1:]) / 2
        
        n_freq_bins = len(freq_centers)
        
        # Initialize power grid
        power_grid = np.zeros((n_spectra, n_freq_bins))
        
        # Interpolate each spectrum onto the regular frequency grid
        for i in range(n_spectra):
            rf_freqs = waterfall.rf_frequencies[i]
            powers = waterfall.powers[i]
            
            # Sort by frequency (required for interpolation)
            sort_idx = np.argsort(rf_freqs)
            rf_freqs_sorted = rf_freqs[sort_idx]
            powers_sorted = powers[sort_idx]
            
            # Remove duplicate frequencies (keep first occurrence)
            # Use small tolerance to handle floating point comparison
            unique_mask = np.concatenate(([True], np.diff(rf_freqs_sorted) > 1e-6))
            rf_freqs_unique = rf_freqs_sorted[unique_mask]
            powers_unique = powers_sorted[unique_mask]
            
            # Interpolate onto regular grid
            # Use linear interpolation, fill out-of-bounds with NaN
            try:
                interp_func = interp1d(rf_freqs_unique, powers_unique, 
                                      kind='linear', 
                                      bounds_error=False, 
                                      fill_value=np.nan)
                power_grid[i, :] = interp_func(freq_centers)
            except Exception as e:
                # If interpolation fails, fill with NaN
                print(f"Warning: Interpolation failed for spectrum {i}: {e}")
                power_grid[i, :] = np.nan
        
        # Create time array (spectrum index for now, could convert to actual time)
        time_array = np.arange(n_spectra)
        
        return time_array, freq_centers, power_grid


def plot_waterfall(waterfall: WaterfallData, 
                   metadata: dict,
                   output_path: Optional[Path] = None,
                   freq_range: Optional[Tuple[float, float]] = None,
                   time_range: Optional[Tuple[int, int]] = None,
                   filter_num: Optional[int] = None,
                   cmap: str = 'inferno',
                   vmin: Optional[float] = None,
                   vmax: Optional[float] = None,
                   interactive: bool = True):
    """
    Create a waterfall/spectrogram plot.
    
    Args:
        waterfall: WaterfallData object
        metadata: Metadata dictionary
        output_path: Save plot to this path (optional)
        freq_range: (min_freq, max_freq) in MHz to plot
        time_range: (start_idx, end_idx) to plot
        cmap: Matplotlib colormap name
        vmin, vmax: Color scale limits
        interactive: Enable interactive zoom/pan (default True)
    """
    # Create gridded data
    time_array, freq_centers, power_grid = create_waterfall_grid(waterfall, freq_range=freq_range, filter_num=filter_num)
    
    # Apply time range if specified
    if time_range:
        start_idx, end_idx = time_range
        time_array = time_array[start_idx:end_idx]
        power_grid = power_grid[start_idx:end_idx, :]
        timestamps = waterfall.timestamps[start_idx:end_idx]
    else:
        timestamps = waterfall.timestamps
    
    # Convert timestamps to datetime objects for y-axis
    from datetime import datetime
    try:
        # Parse timestamps (format: MMDDYYYY_HHMMSS)
        datetime_objs = [datetime.strptime(ts.replace('.fits', ''), '%m%d%Y_%H%M%S') for ts in timestamps]
        # Convert to matplotlib dates
        import matplotlib.dates as mdates
        time_values = mdates.date2num(datetime_objs)
        use_datetime_axis = True
    except:
        # Fallback to indices if parsing fails
        time_values = time_array
        use_datetime_axis = False
    
    # Create figure
    fig, ax = plt.subplots(figsize=(12, 8))
    
    # Use power normalization for better dynamic range visualization
    from matplotlib.colors import PowerNorm
    norm = PowerNorm(gamma=1.0, vmin=vmin, vmax=vmax)
    
    # Plot waterfall
    # With origin='upper', extent should be [xmin, xmax, ymax, ymin] for top-to-bottom
    extent = [freq_centers.min(), freq_centers.max(), 
              time_values.max(), time_values.min()]
    
    im = ax.imshow(power_grid, 
                   aspect='auto',
                   origin='upper',
                   extent=extent,
                   cmap=cmap,
                   norm=norm,
                   interpolation='nearest')
    
    # Labels and title
    ax.set_xlabel('RF Frequency (MHz)', fontsize=12)
    
    if use_datetime_axis:
        ax.set_ylabel('Time (ET)', fontsize=12)
        # Format y-axis to show time
        import matplotlib.dates as mdates
        ax.yaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.yaxis.set_major_locator(mdates.HourLocator(interval=2))
    else:
        ax.set_ylabel('Spectrum Index', fontsize=12)
    
    cycle_id = metadata.get('cycle_id', 'unknown')
    state = metadata.get('state', 'unknown')
    
    # Build title with filter number if available
    if filter_num is not None:
        title = f'Waterfall Plot - {cycle_id} - State {state} - Filter {filter_num}\n'
    else:
        title = f'Waterfall Plot - {cycle_id} - State {state}\n'
    
    title += f'{len(timestamps)} spectra, {timestamps[0]} to {timestamps[-1]}'
    ax.set_title(title, fontsize=14)
    
    # Colorbar
    cbar = plt.colorbar(im, ax=ax, label='Power (dBm)')
    
    # Grid
    ax.grid(True, alpha=0.3)
    
    # Interactive zoom
    if interactive and not output_path:
        # Add navigation toolbar message
        fig.text(0.5, 0.02, 'Use toolbar to zoom/pan. Press "h" to reset view.', 
                ha='center', fontsize=10, style='italic')
        
        # Store original limits for reset
        ax._orig_xlim = ax.get_xlim()
        ax._orig_ylim = ax.get_ylim()
        
        # Add key press event for reset
        def on_key(event):
            if event.key == 'h':  # Home/reset
                ax.set_xlim(ax._orig_xlim)
                ax.set_ylim(ax._orig_ylim)
                fig.canvas.draw()
        
        fig.canvas.mpl_connect('key_press_event', on_key)
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"Saved: {output_path}")
    else:
        plt.show()
    
    return fig, ax


def plot_day_waterfall(day_dir: Path,
                       states: List[str],
                       output_dir: Optional[Path] = None,
                       freq_range: Optional[Tuple[float, float]] = None,
                       time_range: Optional[Tuple[int, int]] = None,
                       calib_dir: Optional[Path] = None,
                       filter_num: Optional[int] = None,
                       reference_spectrum: Optional[str] = None,
                       power_vmin: float = -70.0,
                       power_vmax: float = -20.0,
                       interactive: bool = True,
                       verbose: bool = False):
    """
    Plot waterfall for one or more states from all cycles in a day directory.
    
    Args:
        day_dir: Path to day directory (e.g., 20251106)
        states: List of state names to plot (e.g., ['1', '2', '3'])
        output_dir: Directory to save plots (optional)
        freq_range: (min_freq, max_freq) in MHz (default: 0-250)
        time_range: (start_idx, end_idx) for each state
        calib_dir: Fallback calibration directory (cycle dirs used first)
        filter_num: Optional - process only this filter number (0-20)
        reference_spectrum: Optional reference spectrum for quality checks
        power_vmin: Fixed minimum power level (dBm) for colorbar
        power_vmax: Fixed maximum power level (dBm) for colorbar
        interactive: Enable interactive zoom/pan
        verbose: Print detailed information
    """
    if not day_dir.exists():
        print(f"Error: Directory not found: {day_dir}")
        return
    
    # Set default frequency range if not specified
    if freq_range is None:
        freq_range = (0, 250)  # Default: 0-250 MHz
    
    # Find all cycle directories
    cycle_dirs = sorted([d for d in day_dir.iterdir() if d.is_dir() and d.name.startswith('cycle_')])
    
    if verbose:
        print(f"\nFound {len(cycle_dirs)} cycles in {day_dir.name}")
    
    # For each requested state
    for state in states:
        if verbose:
            print(f"\n{'='*70}")
            print(f"Processing State {state}")
            print(f"{'='*70}")
        
        # Collect all state files across cycles
        state_files = []
        for cycle_dir in cycle_dirs:
            state_file = cycle_dir / f"state_{state}.fits"
            if state_file.exists():
                state_files.append(state_file)
            else:
                # Try alternative naming
                state_file_alt = cycle_dir / f"state_{state}_OC.fits"
                if state_file_alt.exists():
                    state_files.append(state_file_alt)
        
        if not state_files:
            print(f"Warning: No state_{state}.fits files found in any cycle")
            continue
        
        if verbose:
            print(f"Found {len(state_files)} state_{state}.fits files")
        
        # Load and combine all state files
        combined_waterfall = None
        metadata = None
        
        for state_file in state_files:
            # Get cycle directory for this state file
            cycle_dir = state_file.parent
            
            # Load with calibration from cycle directory
            waterfall, meta = load_state_file(state_file, cycle_dir=cycle_dir, 
                                             filter_num=filter_num, 
                                             reference_spectrum=reference_spectrum,
                                             verbose=verbose)
            
            # Skip empty waterfalls (all spectra excluded)
            if len(waterfall.timestamps) == 0:
                if verbose:
                    print(f"  Skipping {cycle_dir.name}: all spectra excluded")
                continue
            
            if combined_waterfall is None:
                combined_waterfall = waterfall
                metadata = meta
            else:
                # Append to existing waterfall (skip if dimensions don't match)
                if waterfall.rf_frequencies.shape[1] != combined_waterfall.rf_frequencies.shape[1]:
                    if verbose:
                        print(f"  Warning: Skipping {cycle_dir.name}: dimension mismatch")
                    continue
                
                # Append to existing waterfall
                combined_waterfall.timestamps.extend(waterfall.timestamps)
                combined_waterfall.rf_frequencies = np.vstack([
                    combined_waterfall.rf_frequencies,
                    waterfall.rf_frequencies
                ])
                combined_waterfall.powers = np.vstack([
                    combined_waterfall.powers,
                    waterfall.powers
                ])
                combined_waterfall.filter_indices = np.vstack([
                    combined_waterfall.filter_indices,
                    waterfall.filter_indices
                ])
        
        if combined_waterfall is None:
            print(f"Warning: No data loaded for state {state}")
            continue
        
        # Calculate and apply normalization (skip for single filter mode)
        if APPLY_FILTER_NORMALIZATION and filter_num is None:
            normalization = calculate_filter_normalization(combined_waterfall)
            if normalization:
                if verbose:
                    print(f"Applying normalization to {len(normalization)} filters")
                # Apply normalization offsets
                for i in range(len(combined_waterfall.timestamps)):
                    powers = combined_waterfall.powers[i]
                    filters = combined_waterfall.filter_indices[i]
                    for j, filt in enumerate(filters):
                        if filt in normalization:
                            powers[j] += normalization[filt]
                    combined_waterfall.powers[i] = powers
        elif filter_num is not None and verbose:
            print(f"Skipping normalization for single filter mode (filter {filter_num})")
        
        # Determine output path
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            if filter_num is not None:
                output_path = output_dir / f"{day_dir.name}_state_{state}_filter_{filter_num}_waterfall.png"
            else:
                output_path = output_dir / f"{day_dir.name}_state_{state}_waterfall.png"
        else:
            output_path = None
        
        # Create waterfall plot
        print(f"\nCreating waterfall plot for state {state}...")
        print(f"  Total spectra: {len(combined_waterfall.timestamps)}")
        print(f"  Time: {combined_waterfall.timestamps[0]} to {combined_waterfall.timestamps[-1]}")
        
        plot_waterfall(combined_waterfall, metadata, output_path, 
                      freq_range=freq_range, time_range=time_range, 
                      filter_num=filter_num, interactive=interactive,
                      vmin=power_vmin, vmax=power_vmax)


def main():
    parser = argparse.ArgumentParser(
        description='Create waterfall/spectrogram plots from consolidated filterbank data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Plot state 1 for November 6
  %(prog)s /path/to/Bandpass_consolidated/20251106 --state 1
  
  # Plot only filter 10 for state 1
  %(prog)s /path/to/Bandpass_consolidated/20251106 --state 1 --filter 10
  
  # Plot multiple states
  %(prog)s /path/to/Bandpass_consolidated/20251106 --state 1 2 3
  
  # Plot with frequency range
  %(prog)s /path/to/Bandpass_consolidated/20251106 --state 1 --freq-range 50 200
  
  # Plot all states and save to directory
  %(prog)s /path/to/Bandpass_consolidated/20251106 --all-states --output ./plots
        """
    )
    
    parser.add_argument('day_dir', type=Path,
                       help='Path to day directory (e.g., 20251106)')
    
    parser.add_argument('--state', '-s', nargs='+', type=str,
                       help='State(s) to plot (e.g., 1 2 3)')
    
    parser.add_argument('--all-states', action='store_true',
                       help='Plot all available states')
    
    parser.add_argument('--freq-range', nargs=2, type=float, metavar=('MIN', 'MAX'),
                       help='RF frequency range to plot in MHz (e.g., 50 200)')
    
    parser.add_argument('--time-range', nargs=2, type=int, metavar=('START', 'END'),
                       help='Spectrum index range to plot (e.g., 0 100)')
    
    parser.add_argument('--output', '-o', type=Path,
                       help='Output directory for saving plots')
    
    parser.add_argument('--calib-dir', type=Path,
                       help='Directory containing filter calibration files')
    
    parser.add_argument('--no-interactive', action='store_true',
                       help='Disable interactive zoom/pan (useful for batch processing)')
    
    parser.add_argument('--filter', '-f', type=int, metavar='N',
                       help='Plot only this filter number (0-20)')
    
    parser.add_argument('--reference-spectrum', type=str, metavar='CYCLE:IDX',
                       help='Reference spectrum for quality checks (e.g., cycle_001:0)')
    
    parser.add_argument('--power-range', nargs=2, type=float, metavar=('VMIN', 'VMAX'),
                       default=[-70.0, -20.0],
                       help='Fixed power range (dBm) for colorbar (e.g., -70 -20)')
    
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Print detailed information')
    
    args = parser.parse_args()
    
    # Validate day directory
    if not args.day_dir.exists():
        print(f"Error: Directory not found: {args.day_dir}")
        sys.exit(1)
    
    # Determine which states to plot
    if args.all_states:
        # Find all unique states from first cycle
        first_cycle = next((d for d in args.day_dir.iterdir() if d.is_dir() and d.name.startswith('cycle_')), None)
        if first_cycle is None:
            print("Error: No cycle directories found")
            sys.exit(1)
        
        state_files = sorted(first_cycle.glob('state_*.fits'))
        states = []
        for sf in state_files:
            # Extract state number from filename
            name = sf.stem  # e.g., 'state_1' or 'state_1_OC'
            if '_OC' in name:
                state_num = name.split('_')[1]
            else:
                state_num = name.split('_')[1]
            if state_num not in states and state_num != 'filtercal':
                states.append(state_num)
    elif args.state:
        states = args.state
    else:
        print("Error: Must specify either --state or --all-states")
        parser.print_help()
        sys.exit(1)
    
    # Convert freq_range to tuple if provided
    freq_range = tuple(args.freq_range) if args.freq_range else None
    time_range = tuple(args.time_range) if args.time_range else None
    
    # Create waterfalls
    plot_day_waterfall(
        args.day_dir,
        states,
        output_dir=args.output,
        freq_range=freq_range,
        time_range=time_range,
        calib_dir=args.calib_dir,
        filter_num=args.filter,
        reference_spectrum=args.reference_spectrum,
        power_vmin=args.power_range[0],
        power_vmax=args.power_range[1],
        interactive=not args.no_interactive,
        verbose=args.verbose
    )


if __name__ == '__main__':
    main()
