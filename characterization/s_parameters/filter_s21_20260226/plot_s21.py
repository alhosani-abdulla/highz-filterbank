#!/usr/bin/env python3
"""
Plot S21 measurements for all 21 cavity filters

Measurement Date: 2026-02-26
Measured by: Abdulla Alhosani
VNA: Keysight E5071C ENA Series Network Analyzer
Settings: -20 dBm output, 70 kHz IF BW, 16x averaging, 1.5% smoothing
"""

import numpy as np
import matplotlib.pyplot as plt
import skrf as rf
from pathlib import Path

# Load all S2P files
s2p_dir = Path(__file__).parent
filters = {}

print("Loading S2P files...")
for filt_num in range(1, 22):
    filename = s2p_dir / f'filter_{filt_num:02d}.s2p'
    if filename.exists():
        filters[filt_num] = rf.Network(str(filename))
        print(f"  Loaded Filter {filt_num}")
    else:
        print(f"  Warning: {filename} not found")

print(f"\nLoaded {len(filters)} filters\n")

# Expected filter centers (904.0 to 956.0 MHz in 2.6 MHz steps)
filter_centers = np.arange(904.0, 956.1, 2.6)

# ============================================================================
# Plot 1: All filters overlaid
# ============================================================================
print("Creating overlaid plot...")
plt.figure(figsize=(14, 8))

for filt_num in range(1, 22):
    if filt_num in filters:
        network = filters[filt_num]
        freq_mhz = network.f / 1e6  # Convert to MHz
        s21_db = network.s_db[:, 1, 0]  # S21 in dB
        
        plt.plot(freq_mhz, s21_db, label=f'Filter {filt_num} ({filter_centers[filt_num-1]:.1f} MHz)', alpha=0.7)

plt.xlabel('Frequency (MHz)', fontsize=12)
plt.ylabel('S21 (dB)', fontsize=12)
plt.title('Filter Bank S21 Measurements - All 21 Filters', fontsize=14, fontweight='bold')
plt.grid(True, alpha=0.3)
plt.xlim(900, 960)
plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left', fontsize=8, ncol=2)
plt.tight_layout()
plt.savefig(s2p_dir / 'filter_s21_overlaid.png', dpi=150, bbox_inches='tight')
print(f"  Saved: {s2p_dir / 'filter_s21_overlaid.png'}")
plt.close()

# ============================================================================
# Plot 2: Individual filters in grid (5x5 subplots)
# ============================================================================
print("Creating grid plot...")
fig, axes = plt.subplots(5, 5, figsize=(18, 16))
axes = axes.flatten()

for idx, filt_num in enumerate(range(1, 22)):
    ax = axes[idx]
    
    if filt_num in filters:
        network = filters[filt_num]
        freq_mhz = network.f / 1e6
        s21_db = network.s_db[:, 1, 0]
        
        ax.plot(freq_mhz, s21_db, 'b-', linewidth=1)
        ax.set_title(f'Filter {filt_num} ({filter_centers[filt_num-1]:.1f} MHz)', fontsize=10, fontweight='bold')
        ax.set_xlabel('Frequency (MHz)', fontsize=8)
        ax.set_ylabel('S21 (dB)', fontsize=8)
        ax.grid(True, alpha=0.3)
        ax.set_xlim(900, 960)
        ax.tick_params(labelsize=8)
        
        # Mark the expected center frequency
        ax.axvline(filter_centers[filt_num-1], color='r', linestyle='--', alpha=0.5, linewidth=0.8)

# Hide extra subplots
for idx in range(21, 25):
    axes[idx].axis('off')

plt.suptitle('Filter Bank S21 Measurements - Individual Filters', fontsize=16, fontweight='bold', y=0.995)
plt.tight_layout()
plt.savefig(s2p_dir / 'filter_s21_grid.png', dpi=150, bbox_inches='tight')
print(f"  Saved: {s2p_dir / 'filter_s21_grid.png'}")
plt.close()

# ============================================================================
# Plot 3: Performance summary (text output)
# ============================================================================
print("\n" + "="*70)
print("Filter Performance Summary:")
print("="*70)
print(f"{'Filter':<8} {'Center (MHz)':<15} {'Peak S21 (dB)':<18} {'Loss at Center (dB)'}")
print("="*70)

for filt_num in range(1, 22):
    if filt_num in filters:
        network = filters[filt_num]
        freq_mhz = network.f / 1e6
        s21_db = network.s_db[:, 1, 0]
        
        # Peak S21
        peak_s21 = np.max(s21_db)
        peak_freq = freq_mhz[np.argmax(s21_db)]
        
        # S21 at expected center frequency
        center_freq = filter_centers[filt_num-1]
        center_idx = np.argmin(np.abs(freq_mhz - center_freq))
        s21_at_center = s21_db[center_idx]
        
        print(f"{filt_num:<8} {center_freq:<15.1f} {peak_s21:<18.2f} {s21_at_center:.2f}")

print("="*70)

# ============================================================================
# Plot 4: Heatmap showing S21 vs frequency for all filters
# ============================================================================
print("\nCreating heatmap...")
freq_common = np.linspace(900, 960, 1601)
s21_matrix = np.zeros((21, len(freq_common)))

for idx, filt_num in enumerate(range(1, 22)):
    if filt_num in filters:
        network = filters[filt_num]
        freq_mhz = network.f / 1e6
        s21_db = network.s_db[:, 1, 0]
        
        # Interpolate to common grid
        s21_matrix[idx, :] = np.interp(freq_common, freq_mhz, s21_db)

plt.figure(figsize=(14, 10))
im = plt.imshow(s21_matrix, aspect='auto', origin='lower', cmap='viridis',
                extent=[freq_common[0], freq_common[-1], 1, 21])
plt.colorbar(im, label='S21 (dB)')
plt.xlabel('Frequency (MHz)', fontsize=12)
plt.ylabel('Filter Number', fontsize=12)
plt.title('Filter Bank S21 Heatmap - All Filters', fontsize=14, fontweight='bold')
plt.yticks(range(1, 22))
plt.grid(False)
plt.tight_layout()
plt.savefig(s2p_dir / 'filter_s21_heatmap.png', dpi=150, bbox_inches='tight')
print(f"  Saved: {s2p_dir / 'filter_s21_heatmap.png'}")
plt.close()

print("\n✓ All plots generated successfully!")
