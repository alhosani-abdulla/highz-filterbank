#!/usr/bin/env python3
"""
Example: Using log detector utilities for filter calibration

This script demonstrates how to use the log detector calibration utilities
to get LO power at specific frequencies and apply corrections to measurements.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utilities.io_utils import (
    LogDetectorCalibration, 
    LOPowerLoader,
    get_lo_power_correction
)

def example_basic_usage():
    """Example: Basic log detector calibration usage"""
    print("="*60)
    print("EXAMPLE 1: Basic Log Detector Calibration")
    print("="*60)
    
    # Load calibration
    calib = LogDetectorCalibration()
    calib.info()
    
    # Convert some example voltages to power
    print("\nConvert voltages to power:")
    voltages = [0.536, 0.700, 0.920]
    for v in voltages:
        power, is_interp = calib.voltage_to_power(v)
        status = "interpolated" if is_interp else "extrapolated"
        print(f"  {v:.3f} V → {power:.2f} dBm ({status})") 
    
    print()


def example_lo_power_from_fits():
    """Example: Load LO power vs frequency from FITS file"""
    print("="*60)
    print("EXAMPLE 2: Load LO Power from Calibration FITS")
    print("="*60)
    
    # Load LO power data from most recent cycle
    cycle_dir = "/media/peterson/INDURANCE/Data/03012026/Cycle_03012026_114"
    fits_file = os.path.join(cycle_dir, "filtercal_-4dBm.fits")
    
    if not os.path.exists(fits_file):
        print(f"File not found: {fits_file}")
        return
    
    # Load LO power vs frequency
    lo_power = LOPowerLoader(fits_file)
    lo_power.info()
    
    # Get power at specific frequencies
    print("\nLO power at specific frequencies:")
    test_freqs = [900, 920, 930, 940, 960]
    for freq in test_freqs:
        power = lo_power.get_power_at_frequency(freq)
        print(f"  {freq:.1f} MHz → {power:.2f} dBm")
    
    print()


def example_filter_calibration():
    """Example: Get LO power corrections for filter calibration"""
    print("="*60)
    print("EXAMPLE 3: Filter Calibration with LO Power Corrections")
    print("="*60)
    
    cycle_dir = "/media/peterson/INDURANCE/Data/03012026/Cycle_03012026_114"
    
    if not os.path.exists(cycle_dir):
        print(f"Cycle directory not found: {cycle_dir}")
        return
    
    # Get LO power correction function
    # This normalizes all frequencies to the mean LO power
    get_correction = get_lo_power_correction(cycle_dir, power_setting='-4dBm', reference='mean')
    
    print(f"Using cycle: {os.path.basename(cycle_dir)}")
    print(f"Power setting: -4 dBm")
    print(f"Reference: mean power across band\n")
    
    # Example: Process filter measurements from different frequencies
    # These are the 21 filter center frequencies (example)
    filter_freqs = [
        903.0, 907.0, 911.0, 915.0, 919.0, 923.0, 927.0,
        931.0, 935.0, 939.0, 943.0, 947.0, 951.0, 955.0,
        959.0, 915.5, 919.5, 923.5, 927.5, 931.5, 935.5
    ]
    
    print("Filter calibration corrections:")
    print(f"{'Filter':>8} {'Freq (MHz)':>12} {'Correction (dB)':>18} {'Application':>20}")
    print("-" * 60)
    
    for i, freq in enumerate(filter_freqs, 1):
        correction = get_correction(freq)
        print(f"  {i:>5}   {freq:>10.1f}   {correction:>15.2f}   {'P_norm = P_meas - corr':>20}")
    
    print("\nTo normalize filter measurements:")
    print("  1. Measure filter output power: P_measured (dBm)")
    print("  2. Get LO correction at filter center freq: correction = get_correction(freq)")
    print("  3. Normalize: P_normalized = P_measured - correction")
    print("  4. Now P_normalized is relative to mean LO power")
    print()


def example_workflow():
    """Example: Complete workflow for processing a cycle"""
    print("="*60)
    print("EXAMPLE 4: Complete Calibration Workflow")
    print("="*60)
    
    cycle_dir = "/media/peterson/INDURANCE/Data/03012026/Cycle_03012026_114"
    
    if not os.path.exists(cycle_dir):
        print(f"Cycle directory not found: {cycle_dir}")
        return
    
    print("STEP 1: Load LO power data")
    print("-" * 40)
    lo_power = LOPowerLoader(os.path.join(cycle_dir, "filtercal_-4dBm.fits"))
    print(f"Loaded {len(lo_power.frequencies)} frequency points")
    print(f"Mean LO power: {lo_power.powers.mean():.2f} dBm")
    print(f"Power variation: {lo_power.powers.std():.2f} dB std dev")
    print()
    
    print("STEP 2: Get power correction function")
    print("-" * 40)
    get_correction = get_lo_power_correction(cycle_dir, power_setting='-4dBm')
    print("Created correction function normalized to mean power")
    print()
    
    print("STEP 3: Example filter measurement processing")
    print("-" * 40)
    # Simulate a filter measurement
    filter_center = 930.0  # MHz
    measured_power = -15.3  # dBm (example measurement)
    
    correction = get_correction(filter_center)
    normalized_power = measured_power - correction
    
    print(f"Filter center frequency: {filter_center:.1f} MHz")
    print(f"Measured output power: {measured_power:.2f} dBm")
    print(f"LO power correction: {correction:.2f} dB")
    print(f"Normalized power: {normalized_power:.2f} dBm")
    print()
    
    print("STEP 4: Process all 21 filters")
    print("-" * 40)
    print("In your calibration code, loop through all filters:")
    print("  for filter_num in range(21):")
    print("      freq = filter_center_frequencies[filter_num]")
    print("      correction = get_correction(freq)")
    print("      normalized_power = measured_power - correction")
    print("      # Now use normalized_power for S21 calculation")
    print()


if __name__ == '__main__':
    print("\n" + "="*60)
    print("LOG DETECTOR CALIBRATION UTILITIES - USAGE EXAMPLES")
    print("="*60 + "\n")
    
    example_basic_usage()
    example_lo_power_from_fits()
    example_filter_calibration()
    example_workflow()
    
    print("="*60)
    print("All examples completed!")
    print("="*60)
