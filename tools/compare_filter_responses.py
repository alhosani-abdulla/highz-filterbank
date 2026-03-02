#!/usr/bin/env python3
"""
Compare Filter Responses at Different Power Levels

Plots filter responses from both +5dBm and -4dBm power settings side-by-side
with the same power scale for direct comparison.
"""

import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from utilities.io_utils import (
    load_filtercal,
    LOPowerLoader,
    FilterDetectorCalibration,
    get_filter_centers,
    adc_counts_to_voltage
)


def load_and_process(cycle_dir, power_setting, apply_s21=True, normalize_lo=True):
    """Load and process filter data for one power setting."""
    cycle_dir = Path(cycle_dir)
    fits_file = cycle_dir / f"filtercal_{power_setting}.fits"
    
    # Load filter calibration data
    cal_data = load_filtercal(fits_file)
    lo_freqs = cal_data['lo_frequencies']  # MHz
    filter_adc = cal_data['data']  # shape: (n_freq, 21)
    
    # Exclude first point
    lo_freqs = lo_freqs[1:]
    filter_adc = filter_adc[1:, :]
    n_freq, n_filters = filter_adc.shape
    
    # Load LO power
    lo_power_loader = LOPowerLoader(fits_file)
    
    # Set S21 directory
    s21_dir = None
    if apply_s21:
        s21_dir = Path(__file__).parent.parent / "characterization" / "s_parameters" / "filter_s21_20260226"
    
    # Load filter detector calibration with S21
    filter_calib = FilterDetectorCalibration(cycle_dir, apply_s21=apply_s21, s21_dir=s21_dir)
    
    # Convert filter ADC to voltage
    filter_voltages = adc_counts_to_voltage(filter_adc, ref=filter_calib.ref_voltage, mode='c_like')
    
    # Convert to power (don't clip yet if normalizing)
    clip_now = not normalize_lo
    filter_power_dbm = filter_calib.voltage_to_power(filter_voltages, clip_to_noise_floor=clip_now)
    
    # Apply LO normalization if requested
    if normalize_lo:
        lo_power_at_freq = lo_power_loader.get_power_at_frequency(lo_freqs)
        
        # Extract nominal power from setting name
        if power_setting == '+5dBm':
            nominal_power = 5.0
        elif power_setting == '-4dBm':
            nominal_power = -4.0
        else:
            nominal_power = 0.0
        
        # Normalize: Response = P_detector - LO_actual + nominal
        filter_response = np.zeros_like(filter_power_dbm)
        for i in range(n_freq):
            filter_response[i, :] = filter_power_dbm[i, :] - lo_power_at_freq[i] + nominal_power
        
        # Apply clipping after normalization for flat noise floor
        mean_lo = np.mean(lo_power_at_freq)
        normalized_floor = filter_calib.detector_noise_floor_dbm - mean_lo + nominal_power
        filter_response = np.maximum(filter_response, normalized_floor)
    else:
        filter_response = filter_power_dbm.copy()
    
    return lo_freqs, filter_response, filter_calib, lo_power_loader


def compare_filter_responses(cycle_dir):
    """Plot both power settings side-by-side."""
    
    print("Loading +5dBm data...")
    lo_freqs_high, response_high, calib_high, lo_high = load_and_process(
        cycle_dir, '+5dBm', apply_s21=True, normalize_lo=True
    )
    
    print("Loading -4dBm data...")
    lo_freqs_low, response_low, calib_low, lo_low = load_and_process(
        cycle_dir, '-4dBm', apply_s21=True, normalize_lo=True
    )
    
    n_filters = response_high.shape[1]
    filter_centers = get_filter_centers(num_filters=21, start_mhz=904.0, step_mhz=2.6)
    
    # Create stacked plot (vertical)
    fig, (ax_high, ax_low) = plt.subplots(2, 1, figsize=(14, 12), sharex=True, sharey=True)
    
    colors = plt.cm.tab20(np.linspace(0, 1, n_filters))
    
    # Plot +5dBm responses (top)
    for filt_num in range(n_filters):
        ax_high.plot(lo_freqs_high, response_high[:, filt_num], 
                    color=colors[filt_num], linewidth=1.0, alpha=0.7,
                    label=f'F{filt_num+1:02d} ({filter_centers[filt_num]:.1f})')
    
    ax_high.set_ylabel('Detector Power (dBm, S21-corrected, LO-normalized)', fontsize=11)
    ax_high.set_title(f'Filter Responses - LO @ +5 dBm\n{Path(cycle_dir).name}', 
                      fontsize=12, fontweight='bold')
    ax_high.grid(True, alpha=0.3)
    ax_high.legend(bbox_to_anchor=(1.02, 1), loc='upper left', fontsize=8, ncol=1)
    
    # Plot -4dBm responses (bottom)
    for filt_num in range(n_filters):
        ax_low.plot(lo_freqs_low, response_low[:, filt_num], 
                   color=colors[filt_num], linewidth=1.0, alpha=0.7,
                   label=f'F{filt_num+1:02d} ({filter_centers[filt_num]:.1f})')
    
    ax_low.set_xlabel('LO Frequency (MHz)', fontsize=11)
    ax_low.set_ylabel('Detector Power (dBm, S21-corrected, LO-normalized)', fontsize=11)
    ax_low.set_title(f'Filter Responses - LO @ -4 dBm\n{Path(cycle_dir).name}', 
                     fontsize=12, fontweight='bold')
    ax_low.grid(True, alpha=0.3)
    ax_low.legend(bbox_to_anchor=(1.02, 1), loc='upper left', fontsize=8, ncol=1)
    
    plt.tight_layout()
    
    # Save plot
    output_path = Path(__file__).parent / f"filter_comparison_{Path(cycle_dir).name}.png"
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"\nComparison plot saved: {output_path}")
    
    # Print statistics comparison
    print("\n" + "="*80)
    print("FILTER RESPONSE COMPARISON (Peak values)")
    print("="*80)
    print(f"{'Filter':>8}  {'Center':>8}  {'-4dBm Peak':>12}  {'+5dBm Peak':>12}  {'Difference':>12}")
    print("-"*80)
    
    for filt_num in range(n_filters):
        peak_low = np.max(response_low[:, filt_num])
        peak_high = np.max(response_high[:, filt_num])
        diff = peak_high - peak_low
        
        print(f"{filt_num+1:>8}  {filter_centers[filt_num]:>8.1f}  {peak_low:>12.2f}  "
              f"{peak_high:>12.2f}  {diff:>12.2f}")
    
    plt.show()


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: compare_filter_responses.py <cycle_directory>")
        print("\nExample:")
        print("  compare_filter_responses.py /media/peterson/INDURANCE/Data/02272026/Cycle_02272026_LO_Test")
        sys.exit(1)
    
    cycle_dir = sys.argv[1]
    compare_filter_responses(cycle_dir)
