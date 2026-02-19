"""
Calibration utilities for filterbank data

Handles S21 corrections from S-parameter files and filter alignment normalization.
"""

import numpy as np
from pathlib import Path
from .fits_loader import get_filter_centers, find_closest_lo_row
from .conversions import adc_counts_to_voltage


def load_s21_corrections(s21_dir):
    """
    Load S21 correction data for all filters from .s2p files.
    
    Parameters
    ----------
    s21_dir : str or Path
        Directory containing filter_XX.s2p files (XX = 00-20)
    
    Returns
    -------
    dict or None
        Dictionary with filter numbers as keys, each containing:
        - 'freqs': ndarray of frequencies (MHz)
        - 's21_db': ndarray of S21 magnitude (dB)
        Returns None if directory doesn't exist or no files found.
    """
    s21_dir = Path(s21_dir)
    
    if not s21_dir.exists():
        print(f"S21 directory not found: {s21_dir}")
        return None
    
    try:
        import skrf as rf
    except ImportError:
        print("Warning: scikit-rf not installed, S21 corrections unavailable")
        return None
    
    s21_data = {}
    
    for filt_num in range(21):
        s2p_file = s21_dir / f"filter_{filt_num:02d}.s2p"
        
        if not s2p_file.exists():
            continue
        
        try:
            # Load the network from S2P file
            network = rf.Network(str(s2p_file))
            
            # Get frequency in MHz
            freqs_mhz = network.frequency.f / 1e6
            
            # Extract S21 (forward transmission)
            s21_complex = network.s[:, 1, 0]
            
            # Convert to magnitude in dB
            s21_mag = np.abs(s21_complex)
            s21_db = 20 * np.log10(s21_mag + 1e-12)
            
            s21_data[filt_num] = {
                'freqs': np.array(freqs_mhz),
                's21_db': np.array(s21_db)
            }
        except Exception as e:
            print(f"Error loading S2P file for filter {filt_num}: {e}")
            continue
    
    if len(s21_data) > 0:
        print(f"Loaded S21 corrections for {len(s21_data)}/21 filters")
        return s21_data
    else:
        return None


def build_filter_calibration(filtercal_pos, filtercal_neg, 
                             pos_power_dbm=0.0, neg_power_dbm=-9.0,
                             s21_data=None, ref_voltage=5.0):
    """
    Build per-filter calibration from +5dBm and -4dBm filtercal measurements.
    
    Creates linear calibration (voltage -> power) for each filter at its center frequency.
    Optionally applies S21 corrections.
    
    Parameters
    ----------
    filtercal_pos : dict
        Output from load_filtercal() for positive power level
    filtercal_neg : dict
        Output from load_filtercal() for negative power level
    pos_power_dbm : float
        Actual power at positive level (default: 0.0 dBm for +5dBm setting)
    neg_power_dbm : float
        Actual power at negative level (default: -9.0 dBm for -4dBm setting)
    s21_data : dict or None
        S21 corrections from load_s21_corrections()
    ref_voltage : float
        Reference voltage for ADC conversion (default: 5.0 V for filtercal)
    
    Returns
    -------
    dict
        Filter calibrations with keys 0-20, each containing:
        - 'slope': dBm per Volt
        - 'intercept': dBm offset
        - 'center_freq': filter center frequency (MHz)
        - 's21_db': S21 loss at center frequency (dB)
        - 'low_v': voltage at low power
        - 'high_v': voltage at high power
    """
    filter_centers = get_filter_centers()
    filter_calibrations = {}
    
    # Convert ADC counts to voltage
    volts_pos = adc_counts_to_voltage(filtercal_pos['data'], ref=ref_voltage)
    volts_neg = adc_counts_to_voltage(filtercal_neg['data'], ref=ref_voltage)
    
    for filt_num in range(21):
        center_freq = filter_centers[filt_num]
        
        # Find closest LO frequency row in each filtercal
        row_pos = find_closest_lo_row(filtercal_pos['lo_frequencies'], center_freq)
        row_neg = find_closest_lo_row(filtercal_neg['lo_frequencies'], center_freq)
        
        # Get voltages at this filter's center frequency
        low_voltage = volts_neg[row_neg, filt_num]
        high_voltage = volts_pos[row_pos, filt_num]
        
        # Get S21 correction if available
        s21_loss_db = 0.0
        if s21_data and filt_num in s21_data:
            s21_freqs = s21_data[filt_num]['freqs']
            s21_db = s21_data[filt_num]['s21_db']
            s21_loss_db = np.interp(center_freq, s21_freqs, s21_db)
        
        # Apply S21 to get power at detector
        low_power_at_detector = neg_power_dbm + s21_loss_db
        high_power_at_detector = pos_power_dbm + s21_loss_db
        
        # Calculate linear calibration: power = slope * voltage + intercept
        voltage_diff = high_voltage - low_voltage
        
        if abs(voltage_diff) < 0.001:
            print(f"Warning: Filter {filt_num} has insufficient voltage range, skipping")
            continue
        
        slope = (high_power_at_detector - low_power_at_detector) / voltage_diff
        intercept = low_power_at_detector - slope * low_voltage
        
        filter_calibrations[filt_num] = {
            'slope': slope,
            'intercept': intercept,
            'low_v': low_voltage,
            'high_v': high_voltage,
            'center_freq': center_freq,
            's21_db': s21_loss_db
        }
    
    if len(filter_calibrations) < 21:
        print(f"Warning: Only calibrated {len(filter_calibrations)}/21 filters")
    
    return filter_calibrations


def apply_calibration_to_spectrum(data_2d, lo_frequencies, filter_calibrations,
                                  ref_voltage=3.27, return_voltages=False):
    """
    Apply per-filter calibration to a spectrum.
    
    Parameters
    ----------
    data_2d : ndarray (n_freq, 21)
        ADC counts data
    lo_frequencies : ndarray (n_freq,)
        LO frequencies for each row (MHz)
    filter_calibrations : dict
        Per-filter calibration from build_filter_calibration()
    ref_voltage : float
        Reference voltage for ADC conversion (default: 3.27 V for measurements)
    return_voltages : bool
        If True, also return voltage array
    
    Returns
    -------
    frequencies : ndarray (n_freq * 21,)
        Sky frequencies (MHz) for each measurement
    powers : ndarray (n_freq * 21,)
        Calibrated power (dBm) for each measurement
    filter_indices : ndarray (n_freq * 21,)
        Filter number (0-20) for each measurement
    voltages : ndarray (n_freq * 21,), optional
        Voltages if return_voltages=True
    """
    filter_centers = get_filter_centers()
    n_freq, n_channels = data_2d.shape
    
    # Convert all data to voltage
    volts_2d = adc_counts_to_voltage(data_2d, ref=ref_voltage)
    
    # Initialize output arrays
    all_frequencies = []
    all_powers = []
    all_voltages = []
    all_filters = []
    
    for freq_idx in range(n_freq):
        lo_freq = lo_frequencies[freq_idx]
        
        for filt_num in range(n_channels):
            # Calculate sky frequency: filter_center - lo_freq
            sky_freq = filter_centers[filt_num] - lo_freq
            
            voltage = volts_2d[freq_idx, filt_num]
            
            # Apply calibration if available
            if filt_num in filter_calibrations:
                slope = filter_calibrations[filt_num]['slope']
                intercept = filter_calibrations[filt_num]['intercept']
                power = slope * voltage + intercept
            else:
                # Fallback: simple estimate if no calibration
                power = -43.5 * voltage + 24.98
            
            all_frequencies.append(sky_freq)
            all_powers.append(power)
            all_voltages.append(voltage)
            all_filters.append(filt_num)
    
    if return_voltages:
        return (np.array(all_frequencies), np.array(all_powers), 
                np.array(all_filters), np.array(all_voltages))
    else:
        return (np.array(all_frequencies), np.array(all_powers), 
                np.array(all_filters))


def calculate_filter_normalization(frequencies, powers, filters, 
                                   freq_min=50, freq_max=80, 
                                   excluded_filters=None):
    """
    Calculate normalization factors (dB offsets) to align filter responses.
    
    Uses data in a specified frequency region to calculate offsets that bring
    all filters to a common level. The same offset is applied across the full spectrum.
    
    Parameters
    ----------
    frequencies : ndarray
        Sky frequencies (MHz)
    powers : ndarray
        Power values (dBm)
    filters : ndarray
        Filter indices (0-20)
    freq_min : float
        Minimum frequency for alignment region (default: 50 MHz)
    freq_max : float
        Maximum frequency for alignment region (default: 80 MHz)
    excluded_filters : list or None
        Filter indices to exclude from normalization
    
    Returns
    -------
    dict or None
        Normalization offset (dB) for each filter, or None if insufficient data
    """
    if excluded_filters is None:
        excluded_filters = []
    
    # Organize data by filter
    filter_data = {}
    for freq, power, filt in zip(frequencies, powers, filters):
        if filt not in filter_data:
            filter_data[filt] = {'freqs': [], 'powers': []}
        filter_data[filt]['freqs'].append(freq)
        filter_data[filt]['powers'].append(power)
    
    # Get valid filters
    valid_filters = [f for f in filter_data.keys() 
                    if f not in excluded_filters and len(filter_data[f]['freqs']) > 1]
    
    if len(valid_filters) < 2:
        print("Not enough valid filters for normalization")
        return None
    
    # Extract data in alignment frequency region for each filter
    region_data = {}
    for filt in valid_filters:
        freqs = np.array(filter_data[filt]['freqs'])
        powers_arr = np.array(filter_data[filt]['powers'])
        
        # Find indices in the frequency region
        mask = (freqs >= freq_min) & (freqs <= freq_max)
        region_powers = powers_arr[mask]
        
        if len(region_powers) > 0:
            # Use mean power in this region for normalization
            region_data[filt] = np.mean(region_powers)
    
    if len(region_data) < 2:
        print(f"Not enough data in frequency region {freq_min}-{freq_max} MHz for normalization")
        return None
    
    # Calculate mean power in region across all filters
    mean_region_power = np.mean(list(region_data.values()))
    
    # Calculate per-filter offset
    normalization = {}
    for filt in region_data:
        # Offset = mean - individual (brings all filters to mean level in region)
        offset = mean_region_power - region_data[filt]
        normalization[filt] = offset
    
    print(f"Calculated normalization for {len(normalization)} filters "
          f"(using {freq_min}-{freq_max} MHz region)")
    print(f"Mean power in region: {mean_region_power:.2f} dBm")
    
    return normalization if len(normalization) > 0 else None
