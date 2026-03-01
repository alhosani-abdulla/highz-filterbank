#!/usr/bin/env python3
"""
Plot LO power vs frequency using log detector calibration data.

This script loads filter calibration FITS files and extracts the log detector
measurements to assess LO power flatness across 900-960 MHz.
Uses interpolation from the calibration curve (monotonic region only).

NOTE: Interpolation is restricted to the monotonic portion of the calibration
curve where voltage decreases smoothly with increasing power. Above ~10 dBm,
the detector saturates and voltage becomes non-monotonic (starts increasing),
making interpolation invalid.
"""

import numpy as np
import matplotlib.pyplot as plt
from astropy.io import fits
from scipy.interpolate import interp1d
import sys
import os

ADC_REFERENCE_VOLTAGE = 2.5         # V
CALIBRATION_FILE = '/home/peterson/highz/highz-filterbank/characterization/log_detector/calibration_20260226.csv'

# Load and prepare calibration data
def load_calibration():
    """
    Load calibration data and create interpolator for monotonic region.
    
    Returns
    -------
    interp_func : callable
        Interpolation function: voltage (V) -> power (dBm)
    v_min, v_max : float
        Valid voltage range for interpolation
    """
    # Load calibration CSV
    calib = np.genfromtxt(CALIBRATION_FILE, delimiter=',', skip_header=7,
                          names=['Power_dBm', 'Voltage_V', 'Std_Dev_V', 'N_Samples'])
    
    # Find monotonic region where detector is working (not noise floor, not saturated)
    # Start from -70 dBm (detector starts working reliably)
    # End where voltage stops decreasing monotonically (detector saturates)
    
    # Find starting point (around -70 dBm or where voltage < 2.0 V)
    start_idx = np.where(calib['Voltage_V'] < 2.0)[0][0]
    
    # Find monotonic region from start point onwards
    # Check where voltage difference becomes non-negative (voltage stops decreasing)
    voltage_diff = np.diff(calib['Voltage_V'][start_idx:])
    non_monotonic = np.where(voltage_diff >= 0)[0]
    
    if len(non_monotonic) > 0:
        # Use data up to first non-monotonic point
        end_idx = start_idx + non_monotonic[0] + 1
        print(f"Using calibration: {calib['Power_dBm'][start_idx]:.1f} to {calib['Power_dBm'][end_idx]:.1f} dBm (monotonic region)")
    else:
        # All data from start is monotonic
        end_idx = len(calib['Power_dBm'])
        print(f"Using calibration: {calib['Power_dBm'][start_idx]:.1f} to {calib['Power_dBm'][-1]:.1f} dBm (all monotonic)")
    
    # Extract monotonic portion
    voltages = calib['Voltage_V'][start_idx:end_idx]
    powers = calib['Power_dBm'][start_idx:end_idx]
    
    # Create interpolator (voltage -> power)
    # Use cubic for smoothness in the smooth regions
    interp_func = interp1d(voltages, powers, kind='cubic', 
                          bounds_error=False, fill_value='extrapolate')
    
    return interp_func, voltages.min(), voltages.max()

# Initialize calibration interpolator
POWER_INTERPOLATOR, V_MIN, V_MAX = load_calibration()

def adc_to_voltage(adc_value, vref=ADC_REFERENCE_VOLTAGE):
    """
    Convert ADC counts to voltage (bipolar mode).
    
    Parameters
    ----------
    adc_value : int or array
        ADC reading in counts
    vref : float
        Reference voltage (default 2.5V)
        
    Returns
    -------
    float or array
        Voltage in volts
    """
    # ADS1263 is 32-bit ADC in bipolar mode: range is -2^31 to +2^31-1
    # Voltage = (adc_value / 2^31) * Vref
    return (adc_value / 2147483648.0) * vref

def voltage_to_power(voltage):
    """
    Convert log detector voltage to power using calibration curve interpolation.
    
    Uses interpolation from monotonic region of calibration curve. This accounts
    for detector compression/nonlinearity while maintaining measurement
    repeatability (standard deviation << voltage step between power levels).
    
    Parameters
    ----------
    voltage : float or array
        Log detector output voltage in volts
        
    Returns
    -------
    power : float or array
        RF power in dBm
    is_interpolated : bool or array
        Whether value was interpolated (True) or extrapolated (False)
    """
    voltage = np.atleast_1d(voltage)
    power = POWER_INTERPOLATOR(voltage)
    is_interpolated = (voltage >= V_MIN) & (voltage <= V_MAX)
    
    if voltage.size == 1:
        return power[0], is_interpolated[0]
    return power, is_interpolated

def load_log_detector_data(fits_path):
    """
    Load log detector data from FITS file.
    
    Parameters
    ----------
    fits_path : str
        Path to FITS file
        
    Returns
    -------
    frequencies : array
        LO frequencies in MHz
    voltages : array
        Log detector voltages in V
    power_dbm : array
        Measured power in dBm
    is_interpolated : array
        True where power was interpolated, False where extrapolated
    """
    with fits.open(fits_path) as hdul:
        # Get data table
        data = hdul[1].data
        
        # Extract log detector ADC values (shape is (1, 301))
        log_detector_adc = data['LOG_DETECTOR'][0]
        
        # Get frequencies from data table
        frequencies = data['LO_FREQUENCIES'][0]
        
        # Convert ADC → voltage → power
        voltages = adc_to_voltage(log_detector_adc)
        power_dbm, is_interp = voltage_to_power(voltages)
        
        return frequencies, voltages, power_dbm, is_interp

def plot_lo_power(cycle_dir):
    """
    Plot LO power and voltage vs frequency for both +5 dBm and -4 dBm sweeps.
    
    Parameters
    ----------
    cycle_dir : str
        Directory containing filtercal_+5dBm.fits and filtercal_-4dBm.fits
    """
    # Load both sweeps
    high_power_path = os.path.join(cycle_dir, 'filtercal_+5dBm.fits')
    low_power_path = os.path.join(cycle_dir, 'filtercal_-4dBm.fits')
    
    if not os.path.exists(high_power_path):
        print(f"Error: {high_power_path} not found")
        return
    if not os.path.exists(low_power_path):
        print(f"Error: {low_power_path} not found")
        return
    
    print(f"Loading: {high_power_path}")
    freq_high, volt_high, power_high, interp_high = load_log_detector_data(high_power_path)
    
    print(f"Loading: {low_power_path}")
    freq_low, volt_low, power_low, interp_low = load_log_detector_data(low_power_path)
    
    # Calculate statistics (excluding first point which may not be settled)
    print("\n" + "="*60)
    print("LO POWER STATISTICS (Calibration Curve Interpolation)")
    print("="*60)
    print(f"\n+5 dBm Sweep (900.2-960 MHz, excluding first point):")
    print(f"  Mean voltage: {np.mean(volt_high[1:]):.4f} V")
    print(f"  Mean power:   {np.mean(power_high[1:]):.2f} dBm")
    print(f"  Std Dev:      {np.std(power_high[1:]):.2f} dB")
    print(f"  Min:          {np.min(power_high[1:]):.2f} dBm @ {freq_high[np.argmin(power_high[1:])+1]:.1f} MHz")
    print(f"  Max:          {np.max(power_high[1:]):.2f} dBm @ {freq_high[np.argmax(power_high[1:])+1]:.1f} MHz")
    print(f"  Peak-Peak:    {np.ptp(power_high[1:]):.2f} dB")
    
    print(f"\n-4 dBm Sweep (900.2-960 MHz, excluding first point):")
    print(f"  Mean voltage: {np.mean(volt_low[1:]):.4f} V")
    print(f"  Mean power:   {np.mean(power_low[1:]):.2f} dBm")
    print(f"  Std Dev:      {np.std(power_low[1:]):.2f} dB")
    print(f"  Min:          {np.min(power_low[1:]):.2f} dBm @ {freq_low[np.argmin(power_low[1:])+1]:.1f} MHz")
    print(f"  Max:          {np.max(power_low[1:]):.2f} dBm @ {freq_low[np.argmax(power_low[1:])+1]:.1f} MHz")
    print(f"  Peak-Peak:    {np.ptp(power_low[1:]):.2f} dB")
    print("="*60 + "\n")
    
    # Create plot with 3 subplots
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
    
    # Plot 1: Voltages (excluding first points)
    ax1.plot(freq_high[1:], volt_high[1:], 'b-', linewidth=1.5, alpha=0.7, label='+5 dBm setting')
    ax1.plot(freq_low[1:], volt_low[1:], 'r-', linewidth=1.5, alpha=0.7, label='-4 dBm setting')
    ax1.set_ylabel('Log Detector Voltage (V)', fontsize=11)
    ax1.set_title('LO Power Flatness: Log Detector Voltage and Calibrated Power vs Frequency (First Point Excluded)', 
                  fontsize=13, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='upper right', fontsize=9)
    # Zoom into the data range
    all_voltages = np.concatenate([volt_high[1:], volt_low[1:]])
    v_margin = 0.05  # 50 mV margin
    ax1.set_ylim(np.min(all_voltages) - v_margin, np.max(all_voltages) + v_margin)
    
    # Plot 2: +5 dBm power (excluding first point)
    ax2.plot(freq_high[1:], power_high[1:], 'b-', linewidth=1.5, label='+5 dBm setting')
    ax2.axhline(np.mean(power_high[1:]), color='b', linestyle=':', alpha=0.5, 
                label=f'Mean: {np.mean(power_high[1:]):.2f} dBm')
    ax2.set_ylabel('LO Power (dBm)', fontsize=11)
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='upper right', fontsize=9)
    
    # Plot 3: -4 dBm power (excluding first point)
    ax3.plot(freq_low[1:], power_low[1:], 'r-', linewidth=1.5, label='-4 dBm setting')
    ax3.axhline(np.mean(power_low[1:]), color='r', linestyle=':', alpha=0.5,
                label=f'Mean: {np.mean(power_low[1:]):.2f} dBm')
    ax3.set_xlabel('LO Frequency (MHz)', fontsize=11)
    ax3.set_ylabel('LO Power (dBm)', fontsize=11)
    ax3.grid(True, alpha=0.3)
    ax3.legend(loc='upper right', fontsize=9)
    
    plt.tight_layout()
    
    # Save plot to current directory (avoid permission issues on external drive)
    cycle_name = os.path.basename(cycle_dir)
    output_path = f'lo_power_vs_frequency_{cycle_name}.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Plot saved: {output_path}")
    
    plt.show()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        # Use today's most recent cycle
        data_dir = '/media/peterson/INDURANCE/Data'
        date_str = '02272026'
        date_path = os.path.join(data_dir, date_str)
        
        if os.path.exists(date_path):
            # Find most recent cycle
            cycles = [d for d in os.listdir(date_path) if d.startswith('Cycle_')]
            if cycles:
                cycles.sort()
                cycle_dir = os.path.join(date_path, cycles[-1])
                print(f"Using most recent cycle: {cycles[-1]}")
            else:
                print(f"Error: No cycles found in {date_path}")
                sys.exit(1)
        else:
            print(f"Error: {date_path} not found")
            sys.exit(1)
    else:
        cycle_dir = sys.argv[1]
    
    plot_lo_power(cycle_dir)
