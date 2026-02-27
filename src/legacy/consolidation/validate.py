#!/usr/bin/env python3
"""
Validate consolidated filterbank data
- Check directory structure
- Verify FITS file integrity
- Compare sample values against originals
- Check metadata completeness
"""

import sys
from pathlib import Path
from astropy.io import fits
import json
import numpy as np
from datetime import datetime

def validate_consolidated_directory(consolidated_base: Path, original_base: Path):
    """Validate all consolidated data"""
    
    print(f"\n{'='*80}")
    print("CONSOLIDATED DATA VALIDATION")
    print(f"{'='*80}\n")
    
    print(f"Consolidated directory: {consolidated_base}")
    print(f"Original directory: {original_base}\n")
    
    # Find all date directories
    date_dirs = sorted([d for d in consolidated_base.iterdir() if d.is_dir() and d.name.isdigit()])
    
    if not date_dirs:
        print("ERROR: No date directories found!")
        return False
    
    print(f"Found {len(date_dirs)} date directories: {[d.name for d in date_dirs]}\n")
    
    total_cycles = 0
    complete_cycles = 0
    partial_cycles = 0
    validation_errors = []
    
    for date_dir in date_dirs:
        print(f"\n{'='*80}")
        print(f"Validating {date_dir.name}")
        print(f"{'='*80}\n")
        
        # Find all cycle directories
        cycle_dirs = sorted([d for d in date_dir.iterdir() if d.is_dir()])
        
        print(f"Found {len(cycle_dirs)} cycles\n")
        total_cycles += len(cycle_dirs)
        
        for cycle_dir in cycle_dirs:
            is_partial = "partial_cycle" in cycle_dir.name
            if is_partial:
                partial_cycles += 1
            else:
                complete_cycles += 1
            
            # Validate this cycle
            errors = validate_cycle(cycle_dir, is_partial)
            if errors:
                validation_errors.extend([(cycle_dir.name, err) for err in errors])
    
    # Summary
    print(f"\n{'='*80}")
    print("VALIDATION SUMMARY")
    print(f"{'='*80}\n")
    
    print(f"Total cycles: {total_cycles}")
    print(f"  Complete: {complete_cycles}")
    print(f"  Partial: {partial_cycles}")
    print(f"\nValidation errors: {len(validation_errors)}")
    
    if validation_errors:
        print("\nERRORS FOUND:")
        for cycle_name, error in validation_errors:
            print(f"  {cycle_name}: {error}")
        return False
    else:
        print("\n✓ All validation checks passed!")
        return True


def validate_cycle(cycle_dir: Path, is_partial: bool) -> list:
    """Validate a single cycle directory. Returns list of errors."""
    errors = []
    
    print(f"  Checking {cycle_dir.name}...")
    
    # Check for metadata file
    metadata_file = cycle_dir / "cycle_metadata.json"
    if not metadata_file.exists():
        errors.append("Missing cycle_metadata.json")
        return errors
    
    # Load and validate metadata
    try:
        with open(metadata_file) as f:
            metadata = json.load(f)
    except Exception as e:
        errors.append(f"Failed to load metadata: {e}")
        return errors
    
    # Check required metadata fields
    required_fields = ["cycle_id", "cycle_number", "date", "start_time", "end_time", 
                      "state_sequence", "total_spectra", "spectra_counts"]
    for field in required_fields:
        if field not in metadata:
            errors.append(f"Missing metadata field: {field}")
    
    # Find all state FITS files
    state_files = sorted(cycle_dir.glob("state_*.fits"))
    
    if len(state_files) == 0:
        errors.append("No state FITS files found")
        return errors
    
    # Expected states for complete cycle
    if not is_partial:
        expected_states = ['0', '1_calibration', '1_sky', '2', '3', '4', '5', '6', '7']
        found_states = [f.stem.replace('state_', '') for f in state_files]
        
        for expected in expected_states:
            if expected not in found_states:
                errors.append(f"Missing state file: state_{expected}.fits")
    
    # Validate each FITS file
    total_spectra_in_files = 0
    for state_file in state_files:
        try:
            with fits.open(state_file) as hdul:
                # Check structure
                if len(hdul) < 2:
                    errors.append(f"{state_file.name}: Missing binary table HDU")
                    continue
                
                # Check primary header
                primary = hdul[0]
                required_headers = ['STATE', 'NSPECTRA', 'DATE', 'TIMEZONE']
                for header in required_headers:
                    if header not in primary.header:
                        errors.append(f"{state_file.name}: Missing header {header}")
                
                # Check table structure
                table = hdul[1]
                required_columns = ['SPECTRUM_INDEX', 'TIMESTAMP', 'LO_FREQUENCY', 'ADC_VALUES']
                for col in required_columns:
                    if col not in table.columns.names:
                        errors.append(f"{state_file.name}: Missing column {col}")
                
                # Check dimensions
                n_spectra = len(table.data)
                total_spectra_in_files += n_spectra
                
                if n_spectra > 0:
                    adc_shape = table.data['ADC_VALUES'][0].shape
                    if adc_shape != (21, 144):
                        errors.append(f"{state_file.name}: Wrong ADC shape {adc_shape}, expected (21, 144)")
                
        except Exception as e:
            errors.append(f"{state_file.name}: Failed to open/validate: {e}")
    
    # Check total spectra count matches metadata
    if 'total_spectra' in metadata:
        if total_spectra_in_files != metadata['total_spectra']:
            errors.append(f"Spectra count mismatch: files={total_spectra_in_files}, metadata={metadata['total_spectra']}")
    
    if errors:
        print(f"    ✗ {len(errors)} error(s)")
    else:
        print(f"    ✓ Valid ({total_spectra_in_files} spectra)")
    
    return errors


def spot_check_values(consolidated_cycle: Path, original_dir: Path, num_checks: int = 3):
    """Spot check a few spectrum values against originals"""
    
    print(f"\n{'='*80}")
    print("SPOT CHECKING VALUES")
    print(f"{'='*80}\n")
    
    # Load metadata to get timestamps
    metadata_file = consolidated_cycle / "cycle_metadata.json"
    with open(metadata_file) as f:
        metadata = json.load(f)
    
    # Pick a state file
    state_file = next(consolidated_cycle.glob("state_2.fits"), None)
    if not state_file:
        print("No state_2.fits found for spot checking")
        return
    
    print(f"Checking {consolidated_cycle.name}/{state_file.name}...\n")
    
    with fits.open(state_file) as hdul:
        table = hdul[1]
        n_spectra = len(table.data)
        
        if n_spectra == 0:
            print("No spectra in file")
            return
        
        # Check first, middle, and last spectrum
        indices_to_check = [0, n_spectra//2, n_spectra-1][:num_checks]
        
        for idx in indices_to_check:
            timestamp = table.data['TIMESTAMP'][idx]
            adc_values_consolidated = table.data['ADC_VALUES'][idx]
            
            # Find original file
            # Timestamp format: "11042025_HHMMSS"
            original_file = original_dir / f"{timestamp}.fits"
            
            if not original_file.exists():
                print(f"  Spectrum {idx}: Original file not found: {original_file.name}")
                continue
            
            # Load original
            with fits.open(original_file) as orig_hdul:
                orig_data = orig_hdul[0].data
                
                # Original is 144x21, consolidated is 21x144 (transposed)
                adc_values_original = orig_data.T
                
                # Compare
                if np.array_equal(adc_values_consolidated, adc_values_original):
                    print(f"  ✓ Spectrum {idx} ({timestamp}): Values match!")
                else:
                    print(f"  ✗ Spectrum {idx} ({timestamp}): VALUES MISMATCH!")
                    print(f"    Max difference: {np.max(np.abs(adc_values_consolidated - adc_values_original))}")


def main():
    consolidated_base = Path("/Users/abdullaalhosani/Projects/highz/Data/LunarDryLake/2025Nov/filterbank/Bandpass/Bandpass_consolidated")
    original_base = Path("/Users/abdullaalhosani/Projects/highz/Data/LunarDryLake/2025Nov/filterbank/Bandpass/11042025")
    
    if not consolidated_base.exists():
        print(f"ERROR: Consolidated directory not found: {consolidated_base}")
        sys.exit(1)
    
    # Validate structure
    success = validate_consolidated_directory(consolidated_base, original_base)
    
    # Spot check values from first cycle
    first_date_dir = sorted([d for d in consolidated_base.iterdir() if d.is_dir() and d.name.isdigit()])[0]
    first_cycle = sorted([d for d in first_date_dir.iterdir() if d.is_dir() and "cycle" in d.name])[0]
    
    if original_base.exists():
        spot_check_values(first_cycle, original_base, num_checks=3)
    
    if success:
        print(f"\n{'='*80}")
        print("✓ VALIDATION COMPLETE - All checks passed!")
        print(f"{'='*80}\n")
    else:
        print(f"\n{'='*80}")
        print("✗ VALIDATION FAILED - See errors above")
        print(f"{'='*80}\n")
        sys.exit(1)


if __name__ == '__main__':
    main()
