#!/usr/bin/env python3
"""
Filter Response Viewer

Visualize filter responses from calibration FITS files with LO power correction
and optional S21 path corrections.
"""

import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import sys
import argparse

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from utilities.io_utils import (
    load_filtercal,
    LogDetectorCalibration,
    LOPowerLoader,
    FilterDetectorCalibration,
    get_filter_centers,
    adc_counts_to_voltage,
    load_s21_corrections
)


def plot_filter_responses(cycle_dir, power_setting='-4dBm', apply_s21=False, 
                         s21_dir=None, normalize_lo_power=False, reference_power='mean', 
                         show_lo_power=True):
    """
    Plot all 21 filter responses with optional LO power correction.
    
    Parameters
    ----------
    cycle_dir : str or Path
        Path to cycle directory containing filtercal files
    power_setting : str
        Which calibration to use: '+5dBm' or '-4dBm'
    apply_s21 : bool
        Whether to apply S21 path corrections
    s21_dir : str or Path, optional
        Directory containing filter S21 .s2p files
    normalize_lo_power : bool
        Whether to normalize by LO power. WARNING: This may introduce artifacts
        if the log detector is not at the same point as the filter inputs.
        Default False - shows raw filter outputs (recommended).
    reference_power : str or float
        Reference power for normalization ('mean', 'median', or value in dBm)
        Only used if normalize_lo_power=True
    show_lo_power : bool
        Whether to show LO power plot
    """
    cycle_dir = Path(cycle_dir)
    fits_file = cycle_dir / f"filtercal_{power_setting}.fits"
    
    if not fits_file.exists():
        print(f"Error: {fits_file} not found")
        return
    
    print(f"\nLoading filter calibration: {fits_file.name}")
    print("-" * 60)
    
    # Load filter calibration data
    cal_data = load_filtercal(fits_file)
    lo_freqs = cal_data['lo_frequencies']  # MHz
    filter_adc = cal_data['data']  # shape: (n_freq, 21)
    n_freq, n_filters = filter_adc.shape
    
    print(f"LO sweep: {lo_freqs[0]:.1f} - {lo_freqs[-1]:.1f} MHz ({n_freq} points)")
    print(f"Filters: {n_filters}")
    
    # Exclude first point (LO settling issue)
    print("Excluding first frequency point...")
    lo_freqs = lo_freqs[1:]
    filter_adc = filter_adc[1:, :]
    n_freq = len(lo_freqs)
    
    # Load LO power vs frequency
    print("\nLoading LO power calibration...")
    lo_power_loader = LOPowerLoader(fits_file)
    
    # Get reference power for normalization (excluding first point)
    if reference_power == 'mean':
        ref_power = np.mean(lo_power_loader.powers[1:])
    elif reference_power == 'median':
        ref_power = np.median(lo_power_loader.powers[1:])
    else:
        ref_power = float(reference_power)
    
    print(f"LO power: mean = {np.mean(lo_power_loader.powers[1:]):.2f} dBm, "
          f"std = {np.std(lo_power_loader.powers[1:]):.2f} dB (excluding first point)")
    
    if normalize_lo_power:
        print(f"Reference power for normalization: {ref_power:.2f} dBm")
        print("WARNING: LO normalization enabled - may introduce artifacts!")
    else:
        print("LO normalization disabled - showing raw filter outputs (recommended)")
    
    # Convert filter ADC counts to power (dBm) using two-point linear calibration
    print("\nConverting filter ADC → Voltage → Power...")
    print("Using two-point linear calibration from filtercal files")
    print("Each filter detector has slightly different transfer function")
    
    # Load filter detector calibration (uses both +5dBm and -4dBm files for 2-point linear fit)
    filter_calib = FilterDetectorCalibration(cycle_dir)
    filter_calib.info()
    print(f"  ADC reference voltage: {filter_calib.ref_voltage:.3f} V")
    
    # Convert filter ADC to voltage using the same reference voltage as calibration
    filter_voltages = adc_counts_to_voltage(filter_adc, ref=filter_calib.ref_voltage, mode='c_like')
    
    # Convert to power using per-filter linear calibration
    filter_power_dbm = filter_calib.voltage_to_power(filter_voltages)
    
    # Optionally apply LO power correction
    if normalize_lo_power:
        print("Applying LO power normalization...")
        lo_power_at_freq = lo_power_loader.get_power_at_frequency(lo_freqs)  # dBm at each LO freq
        
        # For each frequency point, normalize by LO power
        # Filter response (S21-like) = Filter Output Power - LO Input Power
        filter_response = np.zeros_like(filter_power_dbm)
        for i in range(n_freq):
            filter_response[i, :] = filter_power_dbm[i, :] - lo_power_at_freq[i]
    else:
        # Use raw filter output power (no LO normalization)
        filter_response = filter_power_dbm.copy()
    
    # Optionally apply S21 path corrections
    s21_data = None
    if apply_s21:
        if s21_dir is None:
            s21_dir = Path(__file__).parent.parent / "characterization" / "s_parameters" / "filter_s21_20260226"
        
        print(f"\nLoading S21 corrections from: {s21_dir}")
        s21_data = load_s21_corrections(s21_dir)
        
        if s21_data is not None:
            print(f"Loaded S21 for {len(s21_data)} filters")
            print("Applying S21 path corrections (accounting for system loss)...")
            # Apply S21 corrections
            for filt_num in range(n_filters):
                if (filt_num + 1) in s21_data:
                    s21_freqs = s21_data[filt_num + 1]['freqs']
                    s21_db = s21_data[filt_num + 1]['s21_db']
                    
                    # Interpolate S21 to match LO frequencies
                    s21_interp = np.interp(lo_freqs, s21_freqs, s21_db)
                    
                    # Add S21 to get actual power at detector (S21 is negative for loss)
                    # Detector power = LO equivalent power + S21_dB
                    filter_response[:, filt_num] += s21_interp
        else:
            print("Warning: S21 corrections not available")
            apply_s21 = False
    
    # Get filter center frequencies
    filter_centers = get_filter_centers(num_filters=21, start_mhz=904.0, step_mhz=2.6)
    
    # Create plots
    if show_lo_power:
        fig = plt.figure(figsize=(14, 10))
        gs = fig.add_gridspec(3, 1, height_ratios=[1, 2, 2], hspace=0.3)
        
        # Top plot: LO power vs frequency (excluding first point)
        ax_lo = fig.add_subplot(gs[0])
        ax_lo.plot(lo_freqs, lo_power_loader.powers[1:], 'k-', linewidth=1.5, label='LO Power')
        ax_lo.fill_between(lo_freqs, 
                          lo_power_loader.powers[1:] - lo_power_loader.power_uncertainties[1:],
                          lo_power_loader.powers[1:] + lo_power_loader.power_uncertainties[1:],
                          alpha=0.2, color='gray', label='±1σ uncertainty')
        ax_lo.axhline(ref_power, color='r', linestyle='--', alpha=0.5, label=f'Reference: {ref_power:.2f} dBm')
        ax_lo.set_xlabel('Frequency (MHz)', fontsize=10)
        ax_lo.set_ylabel('LO Power (dBm)', fontsize=10)
        ax_lo.set_title(f'LO Power Calibration ({power_setting} setting, first point excluded)', fontsize=11, fontweight='bold')
        ax_lo.grid(True, alpha=0.3)
        ax_lo.legend(loc='best', fontsize=8)
        
        # Middle plot: All filter responses overlaid
        ax_all = fig.add_subplot(gs[1])
        
        # Bottom plot: Individual filter responses (selected subset)
        ax_ind = fig.add_subplot(gs[2])
    else:
        fig, (ax_all, ax_ind) = plt.subplots(2, 1, figsize=(14, 10), sharex=True)
        gs = None
    
    # Plot all filters
    colors = plt.cm.tab20(np.linspace(0, 1, n_filters))
    for filt_num in range(n_filters):
        ax_all.plot(lo_freqs, filter_response[:, filt_num], 
                   color=colors[filt_num], linewidth=1.0, alpha=0.7,
                   label=f'Filter {filt_num+1:02d} ({filter_centers[filt_num]:.1f} MHz)')
    
    # Set y-axis label based on normalization and S21 correction
    if normalize_lo_power:
        ylabel_str = 'Filter Response (dB relative to LO)'
    elif apply_s21 and s21_data is not None:
        ylabel_str = 'Detector Input Power (dBm, S21-corrected)'
    else:
        ylabel_str = 'LO-Equivalent Power (dBm)'
    
    ax_all.set_ylabel(ylabel_str, fontsize=10)
    title_str = f'All Filter Responses - {cycle_dir.name} ({power_setting})\nFirst point excluded'
    
    if normalize_lo_power:
        title_str += ' - LO-normalized'
    else:
        title_str += ' - Raw outputs (no LO normalization)'
    
    if apply_s21:
        title_str += ' with S21 path corrections'
    
    ax_all.set_title(title_str, fontsize=11, fontweight='bold')
    ax_all.grid(True, alpha=0.3)
    ax_all.legend(bbox_to_anchor=(1.02, 1), loc='upper left', fontsize=7, ncol=2)
    
    # Plot subset of individual filters for clarity
    filters_to_show = [0, 5, 10, 15, 20]  # Show filters 1, 6, 11, 16, 21
    for filt_num in filters_to_show:
        ax_ind.plot(lo_freqs, filter_response[:, filt_num],
                   color=colors[filt_num], linewidth=2.0,
                   marker='o', markersize=2, markevery=10,
                   label=f'Filter {filt_num+1:02d} ({filter_centers[filt_num]:.1f} MHz)')
    
    ax_ind.set_xlabel('LO Frequency (MHz)', fontsize=10)
    ax_ind.set_ylabel(ylabel_str, fontsize=10)
    ax_ind.set_title('Selected Filter Responses (every 5th filter)', fontsize=11, fontweight='bold')
    ax_ind.grid(True, alpha=0.3)
    ax_ind.legend(loc='best', fontsize=9)
    
    plt.tight_layout()
    
    # Save plot
    output_name = f"filter_responses_{cycle_dir.name}_{power_setting.replace('dBm', 'dBm').replace('+', 'p').replace('-', 'n')}"
    if normalize_lo_power:
        output_name += "_LO_normalized"
    else:
        output_name += "_raw"
    if apply_s21:
        output_name += "_with_S21"
    output_name += ".png"
    
    output_path = Path(__file__).parent / output_name
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"\nPlot saved: {output_path}")
    
    # Print statistics
    print("\n" + "="*60)
    print("FILTER RESPONSE STATISTICS")
    print("="*60)
    for filt_num in range(n_filters):
        response = filter_response[:, filt_num]
        max_response = np.max(response)
        max_freq = lo_freqs[np.argmax(response)]
        bandwidth_3db = np.sum(response >= (max_response - 3))
        
        print(f"Filter {filt_num+1:2d} (center {filter_centers[filt_num]:.1f} MHz):")
        print(f"  Peak: {max_response:6.2f} dB @ {max_freq:.1f} MHz")
        print(f"  Mean: {np.mean(response):6.2f} dB")
        print(f"  BW (points > -3dB): {bandwidth_3db} freq points")
    
    plt.show()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='View filter responses from calibration FITS files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage - view raw filter outputs (recommended)
  %(prog)s /media/peterson/INDURANCE/Data/MMDDYYYY/Cycle_MMDDYYYY_###
  
  # Use +5dBm calibration
  %(prog)s /path/to/cycle --power +5dBm
  
  # Apply S21 path corrections
  %(prog)s /path/to/cycle --apply-s21
  
  # Hide LO power plot
  %(prog)s /path/to/cycle --no-lo-plot
  
  # ADVANCED: Normalize by LO power (may introduce artifacts)
  %(prog)s /path/to/cycle --normalize-lo-power
  
Note:
  By default, this tool shows RAW filter output powers without LO normalization.
  This is recommended because filter outputs already contain the full system response.
  
  LO normalization should only be used if the log detector is at the same physical
  location as the filter inputs, with identical path losses. Otherwise, normalization
  introduces inverse LO spectrum artifacts into all filter responses.
        """
    )
    
    parser.add_argument('cycle_dir', 
                       help='Path to cycle directory containing filtercal files')
    parser.add_argument('--power', '-p', 
                       choices=['+5dBm', '-4dBm'], 
                       default='-4dBm',
                       help='Which power setting to use (default: -4dBm)')
    parser.add_argument('--normalize-lo-power',
                       action='store_true',
                       help='Normalize filter outputs by LO power (NOT recommended - see Note above)')
    parser.add_argument('--apply-s21', 
                       action='store_true',
                       help='Apply S21 path corrections from .s2p files')
    parser.add_argument('--s21-dir',
                       help='Directory containing S21 .s2p files')
    parser.add_argument('--reference',
                       default='mean',
                       help='Reference power for LO normalization: "mean", "median", or value in dBm (default: mean)')
    parser.add_argument('--no-lo-plot',
                       action='store_true',
                       help='Hide LO power plot')
    
    args = parser.parse_args()
    
    plot_filter_responses(
        cycle_dir=args.cycle_dir,
        power_setting=args.power,
        apply_s21=args.apply_s21,
        s21_dir=args.s21_dir,
        normalize_lo_power=args.normalize_lo_power,
        reference_power=args.reference,
        show_lo_power=not args.no_lo_plot
    )
