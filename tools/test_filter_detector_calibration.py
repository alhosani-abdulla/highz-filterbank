#!/usr/bin/env python3
"""
Test script for FilterDetectorCalibration integration with viewers.

This demonstrates how the new calibration properly accounts for LO power
variation with frequency.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utilities import io_utils


def test_calibration(cycle_dir, apply_s21=False):
    """Test FilterDetectorCalibration on a cycle directory."""
    
    print(f"Testing FilterDetectorCalibration on: {cycle_dir}")
    print(f"Apply S21 corrections: {apply_s21}")
    print("=" * 80)
    
    try:
        # Build calibration using new method
        filter_cal = io_utils.build_filter_detector_calibration(
            cycle_dir=cycle_dir,
            apply_s21=apply_s21
        )
        
        # Print calibration info
        filter_cal.info()
        
        print("\n" + "=" * 80)
        print("Sample voltage-to-power conversions:")
        print("=" * 80)
        
        # Test conversion for a few filters at different voltages
        test_voltages = [0.3, 0.5, 0.7, 1.0, 1.5]
        test_filters = [1, 5, 10, 15, 21]  # 1-indexed
        
        for filt in test_filters:
            print(f"\nFilter {filt} (center: {904.0 + (filt-1)*2.6:.1f} MHz):")
            for voltage in test_voltages:
                power = filter_cal.voltage_to_power(voltage, filter_nums=filt)
                print(f"  {voltage:.2f} V → {power:.2f} dBm")
        
        print("\n" + "=" * 80)
        print("✓ Calibration test successful!")
        print("=" * 80)
        
        return True
        
    except Exception as e:
        print(f"\n✗ Error during calibration test: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_filter_detector_calibration.py <cycle_directory> [--apply-s21]")
        print("\nExample:")
        print("  python test_filter_detector_calibration.py /media/peterson/INDURANCE/Data/02272026/Cycle_02272026_LO_Test")
        print("  python test_filter_detector_calibration.py /media/peterson/INDURANCE/Data/02272026/Cycle_02272026_LO_Test --apply-s21")
        sys.exit(1)
    
    cycle_dir = sys.argv[1]
    apply_s21 = "--apply-s21" in sys.argv
    
    success = test_calibration(cycle_dir, apply_s21)
    sys.exit(0 if success else 1)
