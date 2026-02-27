#!/usr/bin/env python3
"""
Log Detector Calibration Analysis and Plotting

Loads calibration data from CSV and generates plots of the power-to-voltage
transfer function with automatic linear range detection and interpolation-based
conversion for maximum accuracy.
"""

import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from scipy import stats
from scipy.interpolate import interp1d
import sys
import os

def find_linear_range(power_dbm, voltage_v, window_size=5):
    """
    Find the power range with most constant sensitivity (flattest slope).
    
    Returns indices of the best linear region.
    """
    if len(power_dbm) < window_size + 2:
        # Not enough points, use all data
        return 0, len(power_dbm)
    
    # Calculate local sensitivity at each point
    sensitivity = np.gradient(voltage_v, power_dbm)
    
    # Find window with lowest sensitivity variation
    min_variation = np.inf
    best_start = 0
    
    for i in range(len(sensitivity) - window_size):
        window_sens = sensitivity[i:i+window_size]
        variation = np.std(window_sens) / np.abs(np.mean(window_sens))  # Coefficient of variation
        
        if variation < min_variation:
            min_variation = variation
            best_start = i
    
    # Expand window to find full linear region
    # Look for where std dev starts increasing significantly
    threshold = 0.02  # 2% variation threshold
    
    start_idx = best_start
    end_idx = best_start + window_size
    
    # Expand backwards
    while start_idx > 0:
        test_window = sensitivity[start_idx-1:end_idx]
        if np.std(test_window) / np.abs(np.mean(test_window)) > threshold:
            break
        start_idx -= 1
    
    # Expand forwards
    while end_idx < len(sensitivity):
        test_window = sensitivity[start_idx:end_idx+1]
        if np.std(test_window) / np.abs(np.mean(test_window)) > threshold:
            break
        end_idx += 1
    
    return start_idx, end_idx

def load_calibration_data(filename):
    """Load calibration data from CSV file."""
    try:
        data = pd.read_csv(filename, comment='#')
        print(f"Loaded {len(data)} calibration points from {filename}")
        return data
    except Exception as e:
        print(f"ERROR: Could not load file: {e}")
        sys.exit(1)

def plot_calibration(data, output_prefix):
    """Generate calibration plots with automatic linear range detection."""
    
    # Sort by power for cleaner plotting
    data = data.sort_values('Power_dBm')
    
    # Extract data
    power_dbm = data['Power_dBm'].values
    voltage_v = data['Voltage_V'].values
    std_dev_v = data['Std_Dev_V'].values
    
    # Find best linear range
    lin_start, lin_end = find_linear_range(power_dbm, voltage_v)
    
    print(f"\nAutomatic linear range detection:")
    print(f"  Linear range: {power_dbm[lin_start]:.2f} to {power_dbm[lin_end-1]:.2f} dBm")
    print(f"  Using {lin_end - lin_start} points for linear fit")
    
    # Extract linear region data
    power_linear = power_dbm[lin_start:lin_end]
    voltage_linear = voltage_v[lin_start:lin_end]
    
    # Create figure with subplots
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
    
    # ===== Plot 1: Power vs Voltage with error bars =====
    ax1.errorbar(power_dbm, voltage_v, yerr=std_dev_v, 
                 fmt='o', markersize=6, capsize=4, capthick=1.5,
                 color='gray', ecolor='lightgray', alpha=0.6,
                 label='All data')
    
    # Highlight linear region
    ax1.errorbar(power_linear, voltage_linear, 
                 yerr=std_dev_v[lin_start:lin_end],
                 fmt='o', markersize=8, capsize=5, capthick=2,
                 color='darkblue', ecolor='lightblue',
                 label=f'Linear region ({power_linear[0]:.1f} to {power_linear[-1]:.1f} dBm)')
    
    # Perform linear fit on selected region only
    slope, intercept, r_value, p_value, std_err = stats.linregress(power_linear, voltage_linear)
    
    # Plot fit line over linear region
    voltage_fit_linear = slope * power_linear + intercept
    ax1.plot(power_linear, voltage_fit_linear, 'r--', linewidth=3, 
             label=f'Linear fit: V = {slope:.4f}×P + {intercept:.4f}')
    
    # Calculate residuals for linear region
    residuals_linear = voltage_linear - voltage_fit_linear
    rms_residual = np.sqrt(np.mean(residuals_linear**2))
    
    # Create interpolation function for full range
    interp_func = interp1d(power_dbm, voltage_v, kind='cubic', 
                           fill_value='extrapolate', bounds_error=False)
    
    # Plot smooth interpolation
    power_smooth = np.linspace(power_dbm.min(), power_dbm.max(), 500)
    voltage_smooth = interp_func(power_smooth)
    ax1.plot(power_smooth, voltage_smooth, 'g-', linewidth=1, alpha=0.5,
             label='Cubic interpolation (full range)')
    
    ax1.set_xlabel('Input Power (dBm)', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Output Voltage (V)', fontsize=12, fontweight='bold')
    ax1.set_title('Log Detector Power-to-Voltage Transfer Function', 
                  fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend(fontsize=9, loc='best')
    
    # Add statistics text box
    stats_text = f'Linear Region Fit:\n'
    stats_text += f'R² = {r_value**2:.6f}\n'
    stats_text += f'Slope = {slope:.4f} V/dBm\n'
    stats_text += f'       = {slope*1000:.2f} mV/dBm\n'
    stats_text += f'Intercept = {intercept:.4f} V\n'
    stats_text += f'RMS residual = {rms_residual*1000:.3f} mV'
    ax1.text(0.02, 0.98, stats_text, transform=ax1.transAxes,
             fontsize=9, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
    
    # ===== Plot 2: Residuals (linear region only) =====
    ax2.errorbar(power_linear, residuals_linear * 1000, 
                 yerr=std_dev_v[lin_start:lin_end] * 1000,
                 fmt='o', markersize=8, capsize=5, capthick=2,
                 color='darkgreen', ecolor='lightgreen')
    ax2.axhline(y=0, color='r', linestyle='--', linewidth=2, label='Zero residual')
    ax2.axhline(y=rms_residual*1000, color='orange', linestyle=':', linewidth=1.5, 
                label=f'±RMS = {rms_residual*1000:.3f} mV')
    ax2.axhline(y=-rms_residual*1000, color='orange', linestyle=':', linewidth=1.5)
    
    ax2.set_xlabel('Input Power (dBm)', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Residual (mV)', fontsize=12, fontweight='bold')
    ax2.set_title('Linear Fit Residuals (Linear Region)', fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    ax2.legend(fontsize=9, loc='best')
    
    # ===== Plot 3: Sensitivity (derivative) =====
    sensitivity = np.gradient(voltage_v, power_dbm)
    
    ax3.plot(power_dbm, sensitivity * 1000, 'o-', markersize=6, linewidth=2,
             color='purple', label='Measured sensitivity')
    
    # Highlight linear region
    ax3.axvspan(power_linear[0], power_linear[-1], alpha=0.2, color='blue',
                label='Linear region')
    
    ax3.axhline(y=slope*1000, color='r', linestyle='--', linewidth=2,
               label=f'Fit slope = {slope*1000:.2f} mV/dBm')
    
    # Mark the minimum sensitivity point
    min_sens_idx = np.argmin(np.abs(sensitivity))
    ax3.plot(power_dbm[min_sens_idx], sensitivity[min_sens_idx]*1000, 
             'r*', markersize=15, label=f'Min @ {power_dbm[min_sens_idx]:.1f} dBm')
    
    ax3.set_xlabel('Input Power (dBm)', fontsize=12, fontweight='bold')
    ax3.set_ylabel('Sensitivity (mV/dBm)', fontsize=12, fontweight='bold')
    ax3.set_title('Log Detector Sensitivity vs Power', fontsize=14, fontweight='bold')
    ax3.grid(True, alpha=0.3)
    ax3.legend(fontsize=9, loc='best')
    
    # ===== Plot 4: Interpolation Error Analysis =====
    # Compare interpolation to measured values
    voltage_interp = interp_func(power_dbm)
    interp_error = (voltage_v - voltage_interp) * 1000  # Should be nearly zero
    
    ax4.plot(power_dbm, interp_error, 'o', markersize=6, color='brown')
    ax4.axhline(y=0, color='k', linestyle='-', linewidth=1)
    ax4.set_xlabel('Input Power (dBm)', fontsize=12, fontweight='bold')
    ax4.set_ylabel('Interpolation Error (mV)', fontsize=12, fontweight='bold')
    ax4.set_title('Interpolation Accuracy Check', fontsize=14, fontweight='bold')
    ax4.grid(True, alpha=0.3)
    
    interp_note = 'Note: Use interpolation for best\naccuracy across full range.\nLinear fit only valid in highlighted region.'
    ax4.text(0.02, 0.98, interp_note, transform=ax4.transAxes,
             fontsize=9, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8))
    
    plt.tight_layout()
    
    # Save figure
    output_file = f"{output_prefix}_calibration.png"
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"\nSaved plot: {output_file}")
    
    plt.show()
    
    # ===== Print summary statistics =====
    print("\n" + "="*70)
    print("CALIBRATION SUMMARY")
    print("="*70)
    print(f"Number of points:        {len(data)}")
    print(f"Power range (full):      {power_dbm.min():.2f} to {power_dbm.max():.2f} dBm")
    print(f"Voltage range (full):    {voltage_v.min():.6f} to {voltage_v.max():.6f} V")
    print(f"\nLinear Region (auto-detected):")
    print(f"  Power range:           {power_linear[0]:.2f} to {power_linear[-1]:.2f} dBm")
    print(f"  Number of points:      {len(power_linear)}")
    print(f"\nLinear Fit (in linear region only):")
    print(f"  Model:                 V = {slope:.6f} × P + {intercept:.6f}")
    print(f"  Slope:                 {slope:.6f} V/dBm ({slope*1000:.3f} mV/dBm)")
    print(f"  Intercept:             {intercept:.6f} V")
    print(f"  R²:                    {r_value**2:.8f}")
    print(f"  RMS residual:          {rms_residual:.6f} V ({rms_residual*1000:.3f} mV)")
    print(f"  Max residual:          {np.abs(residuals_linear).max():.6f} V ({np.abs(residuals_linear).max()*1000:.3f} mV)")
    print(f"\nSensitivity Analysis:")
    sens_in_linear = sensitivity[lin_start:lin_end]
    print(f"  In linear region:")
    print(f"    Mean:                {np.mean(sens_in_linear)*1000:.3f} mV/dBm")
    print(f"    Std dev:             {np.std(sens_in_linear)*1000:.3f} mV/dBm")
    print(f"    Variation:           {100*np.std(sens_in_linear)/np.abs(np.mean(sens_in_linear)):.2f}%")
    print(f"  Full range:")
    print(f"    Min sensitivity:     {np.min(sensitivity)*1000:.3f} mV/dBm @ {power_dbm[np.argmin(np.abs(sensitivity))]:.1f} dBm")
    print(f"    Max sensitivity:     {np.max(sensitivity)*1000:.3f} mV/dBm")
    print(f"\nMeasurement Uncertainty:")
    print(f"  Mean std dev:          {std_dev_v.mean():.6f} V ({std_dev_v.mean()*1000:.3f} mV)")
    print(f"  Max std dev:           {std_dev_v.max():.6f} V ({std_dev_v.max()*1000:.3f} mV)")
    print("="*70)
    print(f"\nRECOMMENDATION:")
    print(f"  • For measurements in {power_linear[0]:.1f} to {power_linear[-1]:.1f} dBm:")
    print(f"    Use linear conversion: P = (V - {intercept:.6f}) / {slope:.6f}")
    print(f"  • For measurements outside this range:")
    print(f"    Use interpolation (see saved lookup table file)")
    print("="*70)
    
    # Save fit parameters to text file
    fit_file = f"{output_prefix}_fit_parameters.txt"
    with open(fit_file, 'w') as f:
        f.write("Log Detector Calibration Fit Parameters\n")
        f.write("="*70 + "\n\n")
        f.write("LINEAR REGION (Auto-detected best range)\n")
        f.write("-"*70 + "\n")
        f.write(f"Power range:     {power_linear[0]:.2f} to {power_linear[-1]:.2f} dBm\n")
        f.write(f"Number of points: {len(power_linear)}\n\n")
        f.write("LINEAR FIT PARAMETERS\n")
        f.write("-"*70 + "\n")
        f.write(f"Model:           V = slope × P + intercept\n")
        f.write(f"Slope:           {slope:.8f} V/dBm\n")
        f.write(f"                 {slope*1000:.4f} mV/dBm\n")
        f.write(f"Intercept:       {intercept:.8f} V\n")
        f.write(f"R²:              {r_value**2:.10f}\n")
        f.write(f"RMS residual:    {rms_residual:.8f} V\n\n")
        f.write("INVERSE (Voltage to Power):\n")
        f.write(f"P = (V - {intercept:.8f}) / {slope:.8f}\n\n")
        f.write("SENSITIVITY\n")
        f.write("-"*70 + "\n")
        f.write(f"Mean (linear region): {np.mean(sens_in_linear)*1000:.4f} mV/dBm\n")
        f.write(f"Std dev:              {np.std(sens_in_linear)*1000:.4f} mV/dBm\n")
        f.write(f"Variation:            {100*np.std(sens_in_linear)/np.abs(np.mean(sens_in_linear)):.2f}%\n\n")
        f.write("FULL DATA RANGE\n")
        f.write("-"*70 + "\n")
        f.write(f"Power:           {power_dbm.min():.2f} to {power_dbm.max():.2f} dBm\n")
        f.write(f"Voltage:         {voltage_v.min():.6f} to {voltage_v.max():.6f} V\n")
    print(f"\nSaved fit parameters: {fit_file}")
    
    # Save interpolation lookup table
    lookup_file = f"{output_prefix}_lookup_table.csv"
    lookup_df = pd.DataFrame({
        'Power_dBm': power_dbm,
        'Voltage_V': voltage_v,
        'Std_Dev_V': std_dev_v,
        'In_Linear_Region': [(i >= lin_start and i < lin_end) for i in range(len(power_dbm))]
    })
    lookup_df.to_csv(lookup_file, index=False)
    print(f"Saved lookup table: {lookup_file}")
    print(f"\n  Use this for interpolation-based conversion (most accurate!)")
    
    return {
        'slope': slope,
        'intercept': intercept,
        'r_squared': r_value**2,
        'linear_range': (power_linear[0], power_linear[-1]),
        'interpolation_function': interp_func
    }

def main():
    if len(sys.argv) < 2:
        print("Usage: python plot_calibration.py <calibration_csv_file>")
        print("Example: python plot_calibration.py calibration_20260226.csv")
        sys.exit(1)
    
    input_file = sys.argv[1]
    
    if not os.path.exists(input_file):
        print(f"ERROR: File not found: {input_file}")
        sys.exit(1)
    
    # Load data
    data = load_calibration_data(input_file)
    
    # Generate output prefix from input filename
    output_prefix = os.path.splitext(input_file)[0]
    
    # Create plots and get calibration info
    calib_info = plot_calibration(data, output_prefix)
    
    print("\n" + "="*70)
    print("USAGE INSTRUCTIONS")
    print("="*70)
    print("\n1. FOR LINEAR REGION (Most accurate in specified range):")
    print(f"   Power range: {calib_info['linear_range'][0]:.1f} to {calib_info['linear_range'][1]:.1f} dBm")
    print(f"   Conversion: P_dBm = (V_measured - {calib_info['intercept']:.6f}) / {calib_info['slope']:.6f}")
    print("\n2. FOR FULL RANGE (Use interpolation):")
    print(f"   Load the lookup table: {output_prefix}_lookup_table.csv")
    print("   Use scipy.interpolate.interp1d or pandas interpolation")
    print("\n3. EXAMPLE Python code:")
    print("   from scipy.interpolate import interp1d")
    print(f"   import pandas as pd")
    print(f"   data = pd.read_csv('{output_prefix}_lookup_table.csv')")
    print("   # Create forward function (Power -> Voltage)")
    print("   p_to_v = interp1d(data['Power_dBm'], data['Voltage_V'], kind='cubic')")
    print("   # Create inverse function (Voltage -> Power)")
    print("   v_to_p = interp1d(data['Voltage_V'], data['Power_dBm'], kind='cubic')")
    print("   # Use it:")
    print("   measured_voltage = 1.234  # Your ADC reading")
    print("   power_dbm = v_to_p(measured_voltage)")
    print("="*70)

if __name__ == "__main__":
    main()
