#!/usr/bin/env python3
"""
Plot a single spectrum from consolidated data using the waterfall plotter's conversion pipeline.
This allows comparison with historical viewer output.
"""

import argparse
import numpy as np
from astropy.io import fits
from pathlib import Path
import matplotlib.pyplot as plt
import sys

# Import functions from waterfall_plotter
from waterfall_plotter import (
    load_state_file
)


def plot_spectrum(state_file: Path, spectrum_idx: int, filter_num: int, output: Path = None):
    """
    Plot a single spectrum for a specific filter using waterfall plotter conversion.
    
    Args:
        state_file: Path to state FITS file (e.g., cycle_001_*/state_1.fits)
        spectrum_idx: Which spectrum to plot (0-indexed)
        filter_num: Which filter to plot (0-20)
        output: Optional output path for saved plot
    """
    # Get cycle directory (parent of state file)
    cycle_dir = state_file.parent
    
    print(f"Loading from cycle directory: {cycle_dir}")
    
    # Load using waterfall_plotter function - it will find calibrations in cycle_dir
    waterfall, metadata = load_state_file(state_file, cycle_dir=cycle_dir, filter_num=filter_num)
    
    if spectrum_idx >= len(waterfall.timestamps):
        print(f"Error: Spectrum index {spectrum_idx} out of range (max: {len(waterfall.timestamps)-1})")
        return
    
    # Get the data for this spectrum (already converted to power by load_state_file)
    rf_freqs = waterfall.rf_frequencies[spectrum_idx]
    powers = waterfall.powers[spectrum_idx]
    timestamp = waterfall.timestamps[spectrum_idx]
    
    # Calculate filter center
    filter_center = 904.0 + 2.6 * filter_num
    
    # Sort by RF frequency for plotting
    sort_idx = np.argsort(rf_freqs)
    rf_freqs_sorted = rf_freqs[sort_idx]
    powers_sorted = powers[sort_idx]
    
    # Create plot
    fig, ax = plt.subplots(figsize=(12, 6))
    
    ax.plot(rf_freqs_sorted, powers_sorted, 'b-', linewidth=1.5, label=f'Filter {filter_num}')
    ax.set_xlabel('RF Frequency (MHz)', fontsize=12)
    ax.set_ylabel('Power (dBm)', fontsize=12)
    ax.set_title(f'Spectrum from {timestamp}\nFilter {filter_num} (center: {filter_center:.1f} MHz)',
                 fontsize=14)
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # Print stats
    print(f"\nSpectrum statistics:")
    print(f"  Timestamp: {timestamp}")
    print(f"  Filter: {filter_num} (center: {filter_center:.1f} MHz)")
    print(f"  RF frequency range: {rf_freqs_sorted.min():.1f} - {rf_freqs_sorted.max():.1f} MHz")
    print(f"  Power range: {powers_sorted.min():.2f} - {powers_sorted.max():.2f} dBm")
    print(f"  Mean power: {powers_sorted.mean():.2f} dBm")
    
    if output:
        plt.savefig(output, dpi=150, bbox_inches='tight')
        print(f"\nSaved plot to {output}")
    else:
        plt.show()
    
    plt.close()


def main():
    parser = argparse.ArgumentParser(description='Plot single spectrum from consolidated data')
    parser.add_argument('state_file', type=Path, 
                        help='Path to state FITS file (e.g., cycle_001_*/state_1.fits)')
    parser.add_argument('--spectrum-idx', type=int, default=0, 
                        help='Spectrum index to plot (default: 0)')
    parser.add_argument('--filter', type=int, default=10, 
                        help='Filter number to plot (0-20, default: 10)')
    parser.add_argument('--output', type=Path, help='Output file path (optional)')
    
    args = parser.parse_args()
    
    if not args.state_file.exists():
        print(f"Error: State file not found: {args.state_file}")
        return 1
    
    if args.filter < 0 or args.filter > 20:
        print(f"Error: Filter number must be 0-20")
        return 1
    
    plot_spectrum(args.state_file, args.spectrum_idx, args.filter, args.output)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
