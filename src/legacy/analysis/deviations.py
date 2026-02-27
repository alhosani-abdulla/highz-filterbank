#!/usr/bin/env python3
"""
Analyze deviations from reference spectrum across an entire day.
Generates histograms of correlation, mean offset, and variability metrics.
"""

import argparse
import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt
from scipy.interpolate import interp1d
import sys

# Import functions from waterfall_plotter
from waterfall_plotter import load_state_file


def load_reference_spectrum(day_dir: Path, reference_spec: str, state: str, filter_num: int):
    """Load a reference spectrum from a specified cycle and index."""
    # Parse reference_spec (format: "cycle_XXX:idx")
    try:
        cycle_name, idx_str = reference_spec.split(':')
        idx = int(idx_str)
    except ValueError:
        print(f"Error: Invalid reference format '{reference_spec}'. Use 'cycle_XXX:idx'")
        sys.exit(1)
    
    # Find the cycle directory (may have timestamp suffix)
    cycle_dirs = sorted([d for d in day_dir.iterdir() 
                        if d.is_dir() and d.name.startswith(cycle_name)])
    if not cycle_dirs:
        print(f"Error: Reference cycle directory not found matching: {cycle_name}")
        sys.exit(1)
    
    cycle_dir = cycle_dirs[0]  # Take first match
    
    # Load the state file
    state_file = cycle_dir / f"state_{state}.fits"
    if not state_file.exists():
        print(f"Error: Reference state file not found: {state_file}")
        sys.exit(1)
    
    spectra, _ = load_state_file(state_file, cycle_dir=cycle_dir, filter_num=filter_num)
    
    if idx >= len(spectra.timestamps):
        print(f"Error: Reference index {idx} out of range (0-{len(spectra.timestamps)-1})")
        sys.exit(1)
    
    ref_rf_freq = spectra.rf_frequencies[idx]
    ref_power = spectra.powers[idx]
    
    print(f"Loaded reference spectrum from {cycle_dir.name}, spectrum {idx}")
    print(f"  RF range: {ref_rf_freq[0]:.1f} to {ref_rf_freq[-1]:.1f} MHz")
    print(f"  Power range: {np.min(ref_power):.1f} to {np.max(ref_power):.1f} dBm")
    
    return ref_rf_freq, ref_power


def compare_to_reference(rf_freq, power, ref_rf_freq, ref_power):
    """Compare a spectrum to the reference and return metrics."""
    # Sort both by frequency
    ref_sort_idx = np.argsort(ref_rf_freq)
    ref_rf_sorted = ref_rf_freq[ref_sort_idx]
    ref_power_sorted = ref_power[ref_sort_idx]
    
    sort_idx = np.argsort(rf_freq)
    rf_sorted = rf_freq[sort_idx]
    power_sorted = power[sort_idx]
    
    # Interpolate test spectrum onto reference grid
    try:
        interp_func = interp1d(rf_sorted, power_sorted, 
                              kind='linear', bounds_error=False, fill_value=np.nan)
        power_interp = interp_func(ref_rf_sorted)
        
        # Calculate metrics where both have valid data
        valid_mask = ~np.isnan(power_interp)
        if np.sum(valid_mask) < 10:
            return None
        
        # Calculate difference
        diff = power_interp[valid_mask] - ref_power_sorted[valid_mask]
        
        mean_diff = np.mean(diff)
        std_diff = np.std(diff)
        
        # Calculate correlation
        correlation = np.corrcoef(power_interp[valid_mask], ref_power_sorted[valid_mask])[0, 1]
        
        return {
            'mean_diff': mean_diff,
            'std_diff': std_diff,
            'correlation': correlation
        }
        
    except Exception as e:
        return None


def analyze_day(day_dir: Path, state: str, filter_num: int, reference_spec: str):
    """Analyze all spectra from a day and compute deviations from reference."""
    
    # Load reference spectrum
    ref_rf_freq, ref_power = load_reference_spectrum(day_dir, reference_spec, state, filter_num)
    
    # Find all cycles
    cycle_dirs = sorted([d for d in day_dir.iterdir() 
                        if d.is_dir() and d.name.startswith('cycle_')])
    
    print(f"\nAnalyzing {len(cycle_dirs)} cycles...")
    
    # Collect metrics from all spectra
    all_mean_diffs = []
    all_std_diffs = []
    all_correlations = []
    
    for cycle_dir in cycle_dirs:
        state_file = cycle_dir / f"state_{state}.fits"
        if not state_file.exists():
            continue
        
        try:
            spectra, _ = load_state_file(state_file, cycle_dir=cycle_dir, filter_num=filter_num)
            
            for i in range(len(spectra.timestamps)):
                rf_freq = spectra.rf_frequencies[i]
                power = spectra.powers[i]
                
                metrics = compare_to_reference(
                    rf_freq, power,
                    ref_rf_freq, ref_power
                )
                
                if metrics:
                    all_mean_diffs.append(metrics['mean_diff'])
                    all_std_diffs.append(metrics['std_diff'])
                    all_correlations.append(metrics['correlation'])
        
        except Exception as e:
            print(f"Warning: Failed to process {cycle_dir.name}: {e}")
            continue
    
    print(f"Processed {len(all_mean_diffs)} spectra")
    
    return {
        'mean_diffs': np.array(all_mean_diffs),
        'std_diffs': np.array(all_std_diffs),
        'correlations': np.array(all_correlations)
    }


def plot_histograms(metrics, state, filter_num):
    """Create histogram plots of the deviation metrics."""
    
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(f'Deviation from Reference - State {state}, Filter {filter_num}', 
                 fontsize=14, fontweight='bold')
    
    # Mean offset histogram
    ax = axes[0, 0]
    ax.hist(metrics['mean_diffs'], bins=50, edgecolor='black', alpha=0.7)
    ax.axvline(0, color='red', linestyle='--', linewidth=2, label='Zero offset')
    ax.set_xlabel('Mean Offset from Reference (dB)')
    ax.set_ylabel('Count')
    ax.set_title('Mean Power Offset')
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # Add statistics
    mean_val = np.mean(metrics['mean_diffs'])
    median_val = np.median(metrics['mean_diffs'])
    std_val = np.std(metrics['mean_diffs'])
    ax.text(0.02, 0.98, f'Mean: {mean_val:.2f} dB\nMedian: {median_val:.2f} dB\nStd: {std_val:.2f} dB',
            transform=ax.transAxes, verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    # Variability (std) histogram
    ax = axes[0, 1]
    ax.hist(metrics['std_diffs'], bins=50, edgecolor='black', alpha=0.7, color='orange')
    ax.set_xlabel('Std Dev of Difference (dB)')
    ax.set_ylabel('Count')
    ax.set_title('Difference Variability')
    ax.grid(True, alpha=0.3)
    
    # Add statistics
    mean_val = np.mean(metrics['std_diffs'])
    median_val = np.median(metrics['std_diffs'])
    std_val = np.std(metrics['std_diffs'])
    ax.text(0.02, 0.98, f'Mean: {mean_val:.2f} dB\nMedian: {median_val:.2f} dB\nStd: {std_val:.2f} dB',
            transform=ax.transAxes, verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    # Correlation histogram
    ax = axes[1, 0]
    ax.hist(metrics['correlations'], bins=50, edgecolor='black', alpha=0.7, color='green')
    ax.axvline(1.0, color='red', linestyle='--', linewidth=2, label='Perfect correlation')
    ax.set_xlabel('Correlation Coefficient')
    ax.set_ylabel('Count')
    ax.set_title('Correlation with Reference')
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # Add statistics
    mean_val = np.mean(metrics['correlations'])
    median_val = np.median(metrics['correlations'])
    std_val = np.std(metrics['correlations'])
    ax.text(0.02, 0.98, f'Mean: {mean_val:.3f}\nMedian: {median_val:.3f}\nStd: {std_val:.3f}',
            transform=ax.transAxes, verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    # 2D scatter: correlation vs mean offset
    ax = axes[1, 1]
    scatter = ax.scatter(metrics['mean_diffs'], metrics['correlations'], 
                        c=metrics['std_diffs'], cmap='viridis', alpha=0.6, s=20)
    ax.set_xlabel('Mean Offset (dB)')
    ax.set_ylabel('Correlation Coefficient')
    ax.set_title('Correlation vs Offset (colored by variability)')
    ax.grid(True, alpha=0.3)
    cbar = plt.colorbar(scatter, ax=ax)
    cbar.set_label('Std Dev (dB)')
    
    # Add threshold lines (current thresholds)
    ax.axhline(0.85, color='red', linestyle='--', linewidth=1, alpha=0.5, label='Corr threshold')
    ax.axvline(5.0, color='red', linestyle='--', linewidth=1, alpha=0.5, label='Offset threshold')
    ax.axvline(-5.0, color='red', linestyle='--', linewidth=1, alpha=0.5)
    ax.legend()
    
    plt.tight_layout()
    plt.show()


def main():
    parser = argparse.ArgumentParser(
        description='Analyze deviations from reference spectrum across a day'
    )
    parser.add_argument('day_dir', type=Path,
                       help='Path to day directory (e.g., .../20251102)')
    parser.add_argument('--state', type=str, required=True,
                       help='State number to analyze (e.g., 2, 3, 4)')
    parser.add_argument('--filter', type=int, required=True,
                       help='Filter number (0-20)')
    parser.add_argument('--reference-spectrum', type=str, required=True,
                       help='Reference spectrum (format: cycle_XXX:idx)')
    
    args = parser.parse_args()
    
    if not args.day_dir.exists():
        print(f"Error: Day directory not found: {args.day_dir}")
        sys.exit(1)
    
    # Analyze the day
    metrics = analyze_day(args.day_dir, args.state, args.filter, args.reference_spectrum)
    
    # Plot histograms
    plot_histograms(metrics, args.state, args.filter)
    
    # Print summary statistics
    print("\n" + "="*60)
    print("SUMMARY STATISTICS")
    print("="*60)
    print(f"\nMean Offset (dB):")
    print(f"  Mean:   {np.mean(metrics['mean_diffs']):.2f}")
    print(f"  Median: {np.median(metrics['mean_diffs']):.2f}")
    print(f"  Std:    {np.std(metrics['mean_diffs']):.2f}")
    print(f"  Range:  [{np.min(metrics['mean_diffs']):.2f}, {np.max(metrics['mean_diffs']):.2f}]")
    
    print(f"\nVariability (dB):")
    print(f"  Mean:   {np.mean(metrics['std_diffs']):.2f}")
    print(f"  Median: {np.median(metrics['std_diffs']):.2f}")
    print(f"  Std:    {np.std(metrics['std_diffs']):.2f}")
    print(f"  Range:  [{np.min(metrics['std_diffs']):.2f}, {np.max(metrics['std_diffs']):.2f}]")
    
    print(f"\nCorrelation:")
    print(f"  Mean:   {np.mean(metrics['correlations']):.4f}")
    print(f"  Median: {np.median(metrics['correlations']):.4f}")
    print(f"  Std:    {np.std(metrics['correlations']):.4f}")
    print(f"  Range:  [{np.min(metrics['correlations']):.4f}, {np.max(metrics['correlations']):.4f}]")
    
    # Count how many would be flagged with current thresholds
    flagged = (
        (np.abs(metrics['mean_diffs']) > 5.0) |
        (metrics['std_diffs'] > 2.5) |
        (metrics['correlations'] < 0.85)
    )
    print(f"\nWith current thresholds (|offset| > 5.0 dB, variability > 2.5 dB, corr < 0.85):")
    print(f"  {np.sum(flagged)} / {len(flagged)} spectra would be flagged ({100*np.sum(flagged)/len(flagged):.1f}%)")


if __name__ == '__main__':
    main()
