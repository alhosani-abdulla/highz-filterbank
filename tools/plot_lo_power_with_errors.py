#!/usr/bin/env python3
"""
Plot LO power vs frequency with uncertainty bands using log detector calibration.

This script loads filter calibration FITS files and extracts the log detector
measurements to assess LO power flatness across 900-960 MHz, including uncertainty estimates.
"""

import numpy as np
import matplotlib.pyplot as plt
import sys
import os

# Add src to path for utilities import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
from utilities.io_utils import LOPowerLoader


def plot_lo_power_with_errors(cycle_dir):
    """
    Plot LO power and voltage vs frequency with error bars for both +5 dBm and -4 dBm sweeps.
    
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
    lo_high = LOPowerLoader(high_power_path)
    
    print(f"Loading: {low_power_path}")
    lo_low = LOPowerLoader(low_power_path)
    
    # Calculate statistics (excluding first point which may not be settled)
    print("\n" + "="*70)
    print("LO POWER STATISTICS (Calibration Curve Interpolation with Uncertainty)")
    print("="*70)
    
    print(f"\n+5 dBm Sweep (900.2-960 MHz, excluding first point):")
    print(f"  Mean voltage:       {np.mean(lo_high.voltages[1:]):.4f} V")
    print(f"  Mean power:         {np.mean(lo_high.powers[1:]):.2f} dBm")
    print(f"  Std Dev:            {np.std(lo_high.powers[1:]):.2f} dB")
    print(f"  Mean uncertainty:   {np.mean(lo_high.power_uncertainties[1:]):.3f} dB (1-sigma)")
    print(f"  Min:                {np.min(lo_high.powers[1:]):.2f} dBm @ {lo_high.frequencies[np.argmin(lo_high.powers[1:])+1]:.1f} MHz")
    print(f"  Max:                {np.max(lo_high.powers[1:]):.2f} dBm @ {lo_high.frequencies[np.argmax(lo_high.powers[1:])+1]:.1f} MHz")
    print(f"  Peak-Peak:          {np.ptp(lo_high.powers[1:]):.2f} dB")
    
    print(f"\n-4 dBm Sweep (900.2-960 MHz, excluding first point):")
    print(f"  Mean voltage:       {np.mean(lo_low.voltages[1:]):.4f} V")
    print(f"  Mean power:         {np.mean(lo_low.powers[1:]):.2f} dBm")
    print(f"  Std Dev:            {np.std(lo_low.powers[1:]):.2f} dB")
    print(f"  Mean uncertainty:   {np.mean(lo_low.power_uncertainties[1:]):.3f} dB (1-sigma)")
    print(f"  Min:                {np.min(lo_low.powers[1:]):.2f} dBm @ {lo_low.frequencies[np.argmin(lo_low.powers[1:])+1]:.1f} MHz")
    print(f"  Max:                {np.max(lo_low.powers[1:]):.2f} dBm @ {lo_low.frequencies[np.argmax(lo_low.powers[1:])+1]:.1f} MHz")
    print(f"  Peak-Peak:          {np.ptp(lo_low.powers[1:]):.2f} dB")
    print("="*70 + "\n")
    
    # Create plot with 3 subplots
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
    
    # Plot 1: Voltages (excluding first points) - no error bars as voltage uncertainty is tiny
    ax1.plot(lo_high.frequencies[1:], lo_high.voltages[1:], 'b-', linewidth=1.5, alpha=0.7, label='+5 dBm setting')
    ax1.plot(lo_low.frequencies[1:], lo_low.voltages[1:], 'r-', linewidth=1.5, alpha=0.7, label='-4 dBm setting')
    ax1.set_ylabel('Log Detector Voltage (V)', fontsize=11)
    ax1.set_title('LO Power Flatness with Uncertainty Bands (First Point Excluded)', 
                  fontsize=13, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='upper right', fontsize=9)
    # Zoom into the data range
    all_voltages = np.concatenate([lo_high.voltages[1:], lo_low.voltages[1:]])
    v_margin = 0.05  # 50 mV margin
    ax1.set_ylim(np.min(all_voltages) - v_margin, np.max(all_voltages) + v_margin)
    
    # Plot 2: +5 dBm power with uncertainty band (excluding first point)
    freq_h = lo_high.frequencies[1:]
    power_h = lo_high.powers[1:]
    err_h = lo_high.power_uncertainties[1:]
    
    ax2.plot(freq_h, power_h, 'b-', linewidth=1.5, label='+5 dBm setting', zorder=3)
    ax2.fill_between(freq_h, power_h - err_h, power_h + err_h, 
                     color='blue', alpha=0.2, label='±1σ uncertainty')
    ax2.axhline(np.mean(power_h), color='b', linestyle=':', alpha=0.5, 
                label=f'Mean: {np.mean(power_h):.2f} dBm', zorder=2)
    ax2.set_ylabel('LO Power (dBm)', fontsize=11)
    ax2.grid(True, alpha=0.3, zorder=1)
    ax2.legend(loc='upper right', fontsize=9)
    
    # Plot 3: -4 dBm power with uncertainty band (excluding first point)
    freq_l = lo_low.frequencies[1:]
    power_l = lo_low.powers[1:]
    err_l = lo_low.power_uncertainties[1:]
    
    ax3.plot(freq_l, power_l, 'r-', linewidth=1.5, label='-4 dBm setting', zorder=3)
    ax3.fill_between(freq_l, power_l - err_l, power_l + err_l,
                     color='red', alpha=0.2, label='±1σ uncertainty')
    ax3.axhline(np.mean(power_l), color='r', linestyle=':', alpha=0.5,
                label=f'Mean: {np.mean(power_l):.2f} dBm', zorder=2)
    ax3.set_xlabel('LO Frequency (MHz)', fontsize=11)
    ax3.set_ylabel('LO Power (dBm)', fontsize=11)
    ax3.grid(True, alpha=0.3, zorder=1)
    ax3.legend(loc='upper right', fontsize=9)
    
    plt.tight_layout()
    
    # Save plot to current directory
    cycle_name = os.path.basename(cycle_dir)
    output_path = f'lo_power_vs_frequency_{cycle_name}_with_errors.png'
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
    
    plot_lo_power_with_errors(cycle_dir)
