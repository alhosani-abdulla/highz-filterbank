#!/usr/bin/env python3
"""
Add filter calibration files to consolidated cycle directories.

This script finds the matching filter calibration files (+5dBm and -4dBm) for each
consolidated cycle based on timestamp proximity and copies them into the cycle directories.
"""

import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import shutil


def parse_filtercal_filename(filename: str) -> Tuple[datetime, str]:
    """
    Parse filter calibration filename to extract timestamp and power level.
    
    Args:
        filename: Filter calibration filename (e.g., '11012025_010442_+5dBm.fits')
    
    Returns:
        Tuple of (datetime, power_level)
    """
    parts = filename.replace('.fits', '').split('_')
    date_str = parts[0]  # MMDDYYYY
    time_str = parts[1]  # HHMMSS
    power = parts[2]     # +5dBm or -4dBm
    
    # Parse datetime
    month = int(date_str[:2])
    day = int(date_str[2:4])
    year = int(date_str[4:])
    hour = int(time_str[:2])
    minute = int(time_str[2:4])
    second = int(time_str[4:])
    
    dt = datetime(year, month, day, hour, minute, second)
    return dt, power


def find_closest_filtercals(cycle_start: datetime, filtercal_files: List[Path], 
                            max_time_diff_seconds: int = 300) -> Dict[str, Optional[Path]]:
    """
    Find the closest filter calibration files for a given cycle start time.
    
    Args:
        cycle_start: Start time of the cycle
        filtercal_files: List of all available filter calibration files
        max_time_diff_seconds: Maximum time difference in seconds to consider a match
    
    Returns:
        Dict with keys '+5dBm' and '-4dBm' pointing to the closest matching files,
        or None if no match within max_time_diff_seconds
    """
    closest = {'+5dBm': None, '-4dBm': None}
    min_diff = {'+5dBm': float('inf'), '-4dBm': float('inf')}
    
    for filtercal_path in filtercal_files:
        try:
            fc_time, power = parse_filtercal_filename(filtercal_path.name)
            time_diff = abs((fc_time - cycle_start).total_seconds())
            
            if time_diff < min_diff[power] and time_diff <= max_time_diff_seconds:
                min_diff[power] = time_diff
                closest[power] = filtercal_path
        except Exception as e:
            print(f"Warning: Could not parse filter calibration file {filtercal_path.name}: {e}")
            continue
    
    return closest


def add_filter_calibrations(consolidated_dir: Path, filtercal_dir: Path, 
                           max_time_diff_seconds: int = 300, dry_run: bool = False):
    """
    Add filter calibration files to all consolidated cycle directories.
    
    Args:
        consolidated_dir: Root directory containing consolidated data (e.g., Bandpass_consolidated)
        filtercal_dir: Directory containing filter calibration files
        max_time_diff_seconds: Maximum time difference in seconds to consider a match
        dry_run: If True, print what would be done without actually copying files
    """
    # Get all filter calibration files
    filtercal_files = sorted(filtercal_dir.glob('*_*_*.fits'))
    print(f"Found {len(filtercal_files)} filter calibration files in {filtercal_dir}")
    
    # Process each day directory
    day_dirs = sorted([d for d in consolidated_dir.iterdir() if d.is_dir() and d.name.startswith('2025')])
    
    total_cycles = 0
    matched_cycles = 0
    partial_matches = 0
    no_matches = 0
    
    for day_dir in day_dirs:
        print(f"\nProcessing {day_dir.name}...")
        
        # Get all cycle directories for this day
        cycle_dirs = sorted([d for d in day_dir.iterdir() if d.is_dir() and d.name.startswith('cycle_')])
        
        for cycle_dir in cycle_dirs:
            total_cycles += 1
            
            # Read cycle metadata to get start time
            metadata_file = cycle_dir / 'cycle_metadata.json'
            if not metadata_file.exists():
                print(f"  Warning: No metadata file in {cycle_dir.name}")
                continue
            
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)
            
            # Parse cycle start time
            cycle_start = datetime.fromisoformat(metadata['start_time'])
            
            # Find closest filter calibration files
            closest_filtercals = find_closest_filtercals(cycle_start, filtercal_files, max_time_diff_seconds)
            
            # Count matches
            num_matches = sum(1 for fc in closest_filtercals.values() if fc is not None)
            
            if num_matches == 2:
                matched_cycles += 1
                status = "✓"
            elif num_matches == 1:
                partial_matches += 1
                status = "⚠"
            else:
                no_matches += 1
                status = "✗"
            
            # Copy or report
            if dry_run:
                print(f"  {status} {cycle_dir.name}:")
                for power, fc_path in closest_filtercals.items():
                    if fc_path:
                        print(f"      {power}: {fc_path.name}")
                    else:
                        print(f"      {power}: NO MATCH")
            else:
                # Copy the files
                copied_files = []
                for power, fc_path in closest_filtercals.items():
                    if fc_path:
                        dest_path = cycle_dir / f'filtercal_{power}.fits'
                        shutil.copy2(fc_path, dest_path)
                        copied_files.append(power)
                
                if copied_files:
                    print(f"  {status} {cycle_dir.name}: Copied {', '.join(copied_files)}")
                else:
                    print(f"  {status} {cycle_dir.name}: No filter calibrations within {max_time_diff_seconds}s")
    
    # Print summary
    print(f"\n{'='*70}")
    print(f"Summary:")
    print(f"  Total cycles: {total_cycles}")
    print(f"  Full matches (both +5dBm and -4dBm): {matched_cycles}")
    print(f"  Partial matches (only one): {partial_matches}")
    print(f"  No matches: {no_matches}")
    print(f"{'='*70}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Add filter calibration files to consolidated cycle directories',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to see what would be copied
  python add_filter_calibrations.py --dry-run
  
  # Actually copy the files
  python add_filter_calibrations.py
  
  # Use custom time tolerance (default is 300 seconds = 5 minutes)
  python add_filter_calibrations.py --max-time-diff 600
        """
    )
    
    parser.add_argument(
        '--consolidated-dir',
        type=Path,
        default=Path('/Users/abdullaalhosani/Projects/highz/Data/LunarDryLake/2025Nov/filterbank/Bandpass_consolidated'),
        help='Path to consolidated data directory (default: %(default)s)'
    )
    
    parser.add_argument(
        '--filtercal-dir',
        type=Path,
        default=Path('/Users/abdullaalhosani/Projects/highz/Data/LunarDryLake/2025Nov/filterbank/filtercalibrations'),
        help='Path to filter calibration files directory (default: %(default)s)'
    )
    
    parser.add_argument(
        '--max-time-diff',
        type=int,
        default=300,
        help='Maximum time difference in seconds to consider a match (default: %(default)s)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without actually copying files'
    )
    
    args = parser.parse_args()
    
    # Validate directories
    if not args.consolidated_dir.exists():
        print(f"Error: Consolidated directory not found: {args.consolidated_dir}")
        return 1
    
    if not args.filtercal_dir.exists():
        print(f"Error: Filter calibration directory not found: {args.filtercal_dir}")
        return 1
    
    # Run the process
    mode = "DRY RUN" if args.dry_run else "COPYING FILES"
    print(f"\n{'='*70}")
    print(f"Adding Filter Calibrations to Consolidated Cycles - {mode}")
    print(f"{'='*70}")
    print(f"Consolidated directory: {args.consolidated_dir}")
    print(f"Filter calibration directory: {args.filtercal_dir}")
    print(f"Max time difference: {args.max_time_diff} seconds")
    if args.dry_run:
        print("DRY RUN MODE - No files will be copied")
    print(f"{'='*70}\n")
    
    add_filter_calibrations(
        args.consolidated_dir,
        args.filtercal_dir,
        args.max_time_diff,
        args.dry_run
    )
    
    return 0


if __name__ == '__main__':
    exit(main())
