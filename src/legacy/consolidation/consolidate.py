#!/usr/bin/env python3
"""
Consolidate Filterbank Data to Image Cube Format

This script converts existing individual spectrum FITS files into consolidated
cycle-based directories with state-separated image cube format files.

Each measurement (3.2 seconds) produces a 21x144 image cube:
- 21 cavity filters (3 detectors × 7 filters each)
- 144 LO frequency sweep points

Data is stored as flattened 3024-element arrays (21×144) in FITS binary tables.
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np
from astropy.io import fits
from astropy.time import Time
from typing import List, Dict, Tuple, Optional


def get_antenna_info(timestamp: datetime) -> Dict[str, str]:
    """
    Determine which antenna was in use based on timestamp.
    
    Uses site visit times from field timeline to determine antenna changes.
    Antenna changes occurred during site visits (between arrival and departure).
    We use the midpoint of each site visit as the antenna change boundary.
    
    Timeline (Nevada local time after DST ended → EDT spectrometer time):
    - Nov 3: Arrived 7:58 AM (PST) = 10:58 AM EDT, Left 10:11 AM = 1:11 PM EDT
      Midpoint: 12:05 PM EDT → Changed from Antenna 4 to Antenna 3
    - Nov 4: Arrived 10:55 AM (PST) = 1:55 PM EDT, Left 12:09 PM = 3:09 PM EDT  
      Midpoint: 2:32 PM EDT → Changed from Antenna 3 to Antenna 2
    - Nov 5: Arrived 1:42 PM (PST) = 4:42 PM EDT, Left 2:57 PM = 5:57 PM EDT
      Midpoint: 5:20 PM EDT → Changed from Antenna 2 to Antenna 1 (+ 34 MHz HPF)
    
    Returns:
        Dict with 'antenna_id', 'antenna_size', and 'notes'
    """
    # Site visit midpoints define antenna change boundaries (all in EDT)
    # Nov 1: Initial setup with Antenna 4 at 1:29 PM (Nevada) = 5:29 PM EDT
    # Nov 3: Change to Antenna 3 at midpoint of 10:58 AM - 1:11 PM EDT = 12:05 PM EDT
    # Nov 4: Change to Antenna 2 at midpoint of 1:55 PM - 3:09 PM EDT = 2:32 PM EDT  
    # Nov 5: Change to Antenna 1 at midpoint of 4:42 PM - 5:57 PM EDT = 5:20 PM EDT
    
    antenna_periods = [
        (datetime(2025, 11, 1, 17, 29), datetime(2025, 11, 3, 12, 5), 
         {'antenna_id': '4', 'antenna_size': '10m', 'notes': 'Largest antenna'}),
        (datetime(2025, 11, 3, 12, 5), datetime(2025, 11, 4, 14, 32), 
         {'antenna_id': '3', 'antenna_size': '7m', 'notes': 'Second largest antenna'}),
        (datetime(2025, 11, 4, 14, 32), datetime(2025, 11, 5, 17, 20), 
         {'antenna_id': '2', 'antenna_size': '5m', 'notes': 'Medium antenna'}),
        (datetime(2025, 11, 5, 17, 20), datetime(2025, 11, 6, 19, 28), 
         {'antenna_id': '1', 'antenna_size': '3m', 'notes': 'Smallest antenna with 34 MHz HPF'}),
    ]
    
    for start, end, info in antenna_periods:
        if start <= timestamp < end:
            return info
    
    # Default if outside known range
    return {'antenna_id': 'Unknown', 'antenna_size': 'Unknown', 'notes': 'Outside documented observation period'}


class SpectrumData:
    """Container for a single spectrum measurement"""
    def __init__(self, fits_file: Path):
        self.file_path = fits_file
        self.data_cube = None  # Will be 21x144 array
        self.timestamp = None
        self.state = None
        self.sysvolt = None
        self.lo_frequencies = None  # Full LO sweep array (144 or 301 points)
        
    def load(self):
        """Load spectrum from FITS file and reshape to data cube
        
        Handles both regular spectra (144 rows, 21x144 cube) and filter calibrations (301 rows, 21x301 cube).
        Regular spectra: LO sweep with SWITCH STATE column
        Filter calibrations: 900-960 MHz sweep in 0.2 MHz steps with POWER_DBM column
        """
        with fits.open(self.file_path) as hdul:
            data = hdul[1].data
            
            # Check if this is a filter calibration file (has POWER_DBM instead of SWITCH STATE)
            is_filtercal = 'POWER_DBM' in data.dtype.names
            
            # Extract LO sweep measurements
            n_points = len(data)  # 144 for regular, 301 for filtercal
            adhat1 = np.array([row['ADHAT_1'] for row in data])  # Nx7
            adhat2 = np.array([row['ADHAT_2'] for row in data])  # Nx7
            adhat3 = np.array([row['ADHAT_3'] for row in data])  # Nx7
            
            # Reshape to 21xN: stack detectors sequentially
            # Detector 1: filters 0-6, Detector 2: filters 7-13, Detector 3: filters 14-20
            self.data_cube = np.concatenate([
                adhat1.T,  # 7xN
                adhat2.T,  # 7xN  
                adhat3.T   # 7xN
            ], axis=0)  # Result: 21xN (21x144 for regular, 21x301 for filtercal)
            
            # Extract metadata from first row
            first_row = data[0]
            self.timestamp = first_row['TIME_RPI2'].strip()
            
            # Get state - filter calibrations use POWER_DBM value
            if is_filtercal:
                power_dbm = first_row['POWER_DBM'].strip()
                self.state = f'filtercal_{power_dbm}dBm'  # e.g., 'filtercal_+5dBm' or 'filtercal_-4dBm'
            else:
                self.state = first_row['SWITCH STATE'].strip()
            
            # Get frequency from first row
            try:
                # Store the full LO frequency sweep array
                self.lo_frequencies = np.array([float(row['FREQUENCY']) for row in data])
            except (ValueError, TypeError, KeyError):
                # Fallback: reconstruct typical LO sweep based on number of points
                if n_points == 144:
                    # Regular spectrum: 650 MHz start, 2 MHz steps, 144 points
                    self.lo_frequencies = 650 + 2.0 * np.arange(n_points)
                elif n_points == 301:
                    # Filter cal: 900 MHz start, 0.2 MHz steps, 301 points
                    self.lo_frequencies = 900 + 0.2 * np.arange(n_points)
                else:
                    self.lo_frequencies = np.full(n_points, 882.0)  # Default fallback
            
            # Get system voltage from header
            try:
                self.sysvolt = hdul[0].header.get('SYSVOLT', 11.167)
            except:
                self.sysvolt = 11.167
                
        return self


class CycleDetector:
    """Detect cycle boundaries from state sequences"""
    
    # Expected cycle sequence: 2→3→4→5→6→7→1(cal)→0→1(sky)
    # Typical cycle duration: ~18.2 minutes
    # Each state ~6 measurements except sky (~280 measurements)
    
    EXPECTED_STATE_SEQUENCE = ['2', '3', '4', '5', '6', '7', '1', '0', '1']
    MAX_TIME_GAP = timedelta(minutes=30)  # Safety: gap > 30 min = definitely new cycle
    
    @staticmethod
    def parse_timestamp(ts_str: str) -> datetime:
        """Parse timestamp from FITS file (MMDDYYYY_HHMMSS format)"""
        # Example: "11042025_040632" or "11042025_040632.fits"
        # Strip .fits extension if present
        ts_clean = ts_str.replace('.fits', '').strip()
        
        try:
            return datetime.strptime(ts_clean, "%m%d%Y_%H%M%S")
        except ValueError:
            # Try ISO format
            return datetime.fromisoformat(ts_clean.replace('Z', '+00:00'))
    
    @staticmethod
    def group_by_cycles(spectra: List[SpectrumData]) -> Dict[int, List[SpectrumData]]:
        """Group spectra into cycles based on state sequence progression"""
        # Sort by timestamp to ensure chronological order
        spectra_sorted = sorted(spectra, key=lambda s: CycleDetector.parse_timestamp(s.timestamp))
        
        cycles = defaultdict(list)
        current_cycle = 0
        prev_state = None
        prev_time = None
        
        # Track state sequence progression
        # Expected: 2→3→4→5→6→7→1(cal)→0→1(sky)
        state_sequence = []
        in_calibration_1 = False
        
        for spectrum in spectra_sorted:
            curr_state = spectrum.state
            curr_time = CycleDetector.parse_timestamp(spectrum.timestamp)
            
            # Check for large time gap (indicates new cycle)
            if prev_time and (curr_time - prev_time) > CycleDetector.MAX_TIME_GAP:
                current_cycle += 1
                state_sequence = []
                in_calibration_1 = False
            
            # Detect cycle boundary based on state progression
            # New cycle starts when we see state '2' after completing full sequence
            elif curr_state == '2' and prev_state is not None:
                # Check if we've seen a complete sequence (should have seen sky state '1' after state '0')
                if len(state_sequence) > 0 and '0' in state_sequence and in_calibration_1:
                    # We've completed a cycle, start new one
                    current_cycle += 1
                    state_sequence = []
                    in_calibration_1 = False
            
            # Track state sequence
            if len(state_sequence) == 0 or curr_state != state_sequence[-1]:
                state_sequence.append(curr_state)
            
            # Track when we're in calibration state 1 (comes before state 0)
            if curr_state == '1' and prev_state == '7':
                in_calibration_1 = True
            
            cycles[current_cycle].append(spectrum)
            prev_state = curr_state
            prev_time = curr_time
            
        return dict(cycles)


class ConsolidatedWriter:
    """Write consolidated FITS files in image cube format"""
    
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    def write_state_file(self, state: str, spectra: List[SpectrumData], cycle_id: str, antenna_info: Dict[str, str]) -> Path:
        """Write consolidated FITS file for one state with image cube format"""
        
        # Determine filename and actual state number
        if state == '1_OC':
            filename = 'state_1_OC.fits'
            state_num = '1'
        elif state == '1':
            filename = 'state_1.fits'
            state_num = '1'
        elif state.startswith('filtercal_'):
            # Filter calibration file: state is like 'filtercal_+5dBm' or 'filtercal_-4dBm'
            power = state.replace('filtercal_', '')  # Get '+5dBm' or '-4dBm'
            filename = f'filtercal_{power}.fits'
            state_num = state  # Keep full state name for header
        else:
            filename = f'state_{state}.fits'
            state_num = state
            
        filepath = self.output_dir / filename
        
        # Prepare data arrays
        num_spectra = len(spectra)
        
        # Determine N_LO_PTS from first spectrum's data cube shape
        # Regular spectra: 21x144=3024, Filter calibrations: 21x301=6321
        n_lo_pts = spectra[0].data_cube.shape[1]
        data_size = 21 * n_lo_pts  # 3024 for regular, 6321 for filtercal
        
        data_cubes = np.zeros((num_spectra, data_size), dtype=np.int64)
        timestamps = np.empty(num_spectra, dtype='U25')
        indices = np.arange(num_spectra, dtype=np.int32)
        voltages = np.zeros(num_spectra, dtype=np.float32)
        lo_freq_arrays = np.zeros((num_spectra, n_lo_pts), dtype=np.float32)
        
        for i, spectrum in enumerate(spectra):
            # Flatten 21xN to data_size (row-major order)
            data_cubes[i] = spectrum.data_cube.ravel()
            timestamps[i] = spectrum.timestamp
            voltages[i] = spectrum.sysvolt
            lo_freq_arrays[i] = spectrum.lo_frequencies
            
        # Create FITS file
        primary_hdu = fits.PrimaryHDU()
        
        # Add header keywords
        primary_hdu.header['CYCLE_ID'] = (cycle_id, 'Observing cycle identifier')
        primary_hdu.header['STATE'] = (state_num, 'Switch state number')
        primary_hdu.header['N_FILTERS'] = (21, 'Number of cavity filters')
        primary_hdu.header['N_LO_PTS'] = (n_lo_pts, 'Number of LO sweep points')
        primary_hdu.header['N_SPECTRA'] = (num_spectra, 'Total spectra in this state')
        primary_hdu.header['DATA_FMT'] = ('image_cube', 'Data format version')
        primary_hdu.header['SYSVOLT'] = (float(np.mean(voltages)), 'Mean system voltage')
        primary_hdu.header['TIMEZONE'] = ('EDT (GMT-4)', 'Timezone for timestamps')
        
        # Add antenna information
        primary_hdu.header['ANTENNA'] = (antenna_info['antenna_id'], 'Antenna identifier (1-4)')
        primary_hdu.header['ANT_SIZE'] = (antenna_info['antenna_size'], 'Antenna aperture diameter')
        primary_hdu.header['ANT_NOTE'] = (antenna_info['notes'], 'Antenna configuration notes')
        
        # Create binary table columns
        col1 = fits.Column(name='DATA_CUBE', format=f'{data_size}J', array=data_cubes, 
                          unit='ADC counts')
        col2 = fits.Column(name='SPECTRUM_TIMESTAMP', format='25A', array=timestamps,
                          unit='ISO 8601')
        col3 = fits.Column(name='SPECTRUM_INDEX', format='1J', array=indices,
                          unit='index')
        col4 = fits.Column(name='SYSVOLT', format='1E', array=voltages,
                          unit='volts')
        col5 = fits.Column(name='LO_FREQUENCIES', format=f'{n_lo_pts}E', array=lo_freq_arrays,
                          unit='MHz')
        
        cols = fits.ColDefs([col1, col2, col3, col4, col5])
        table_hdu = fits.BinTableHDU.from_columns(cols, name='IMAGE CUBE DATA')
        
        # Write FITS file
        hdul = fits.HDUList([primary_hdu, table_hdu])
        hdul.writeto(filepath, overwrite=True)
        
        print(f"  Written {filename}: {num_spectra} spectra")
        return filepath
        
    def write_metadata(self, cycle_num: int, spectra_by_state: Dict[str, List[SpectrumData]], 
                      cycle_id: str, antenna_info: Dict[str, str], notes: dict = None) -> Path:
        """Generate cycle_metadata.json"""
        
        # Calculate statistics
        all_spectra = [s for spectra_list in spectra_by_state.values() 
                      for s in spectra_list]
        
        timestamps = [CycleDetector.parse_timestamp(s.timestamp) for s in all_spectra]
        start_time = min(timestamps)
        end_time = max(timestamps)
        duration = (end_time - start_time).total_seconds() / 60.0  # minutes
        
        voltages = [s.sysvolt for s in all_spectra]
        
        # Build state counts
        spectra_counts = {}
        state_sequence = []
        
        for state in sorted(spectra_by_state.keys(), key=lambda x: (x != '0', x)):
            count = len(spectra_by_state[state])
            
            if state == '1' and count > 50:
                spectra_counts['state_1_sky'] = count
                state_sequence.append('1_sky')
            elif state == '1':
                spectra_counts['state_1_calibration'] = count
                state_sequence.append('1_calibration')
            else:
                spectra_counts[f'state_{state}'] = count
                state_sequence.append(state)
                
        # Metadata structure
        metadata = {
            "cycle_id": cycle_id,
            "cycle_number": cycle_num + 1,
            "date": start_time.strftime("%Y-%m-%d"),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "timezone": "EDT (GMT-4)",
            "duration_minutes": round(duration, 2),
            "antenna": {
                "antenna_id": antenna_info['antenna_id'],
                "antenna_size": antenna_info['antenna_size'],
                "notes": antenna_info['notes']
            },
            "state_sequence": state_sequence,
            "spectra_counts": spectra_counts,
            "total_spectra": len(all_spectra),
            "total_adc_values": len(all_spectra) * 3024,
            "lo_frequencies_range": [
                round(float(np.min([s.lo_frequencies.min() for s in all_spectra])), 2),
                round(float(np.max([s.lo_frequencies.max() for s in all_spectra])), 2)
            ],
            "system_voltage_stats": {
                "mean": round(float(np.mean(voltages)), 3),
                "min": round(float(np.min(voltages)), 3),
                "max": round(float(np.max(voltages)), 3)
            },
            "data_format_version": "1.0",
            "notes": "Consolidated from individual spectrum FITS files into image cube format"
        }
        
        # Add cycle quality notes if provided
        if notes:
            metadata["cycle_quality"] = notes
        
        # Write JSON
        metadata_path = self.output_dir / 'cycle_metadata.json'
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
            
        print(f"  Written cycle_metadata.json")
        return metadata_path


def load_spectra_from_directory(directory: Path) -> List[SpectrumData]:
    """Load all FITS spectra from a directory."""
    fits_files = sorted(directory.glob("*.fits"))
    spectra = []
    
    if not fits_files:
        return spectra
    
    for i, fits_file in enumerate(fits_files):
        try:
            spectrum = SpectrumData(fits_file).load()
            spectra.append(spectrum)
        except Exception as e:
            print(f"  WARNING: Failed to load {fits_file.name}: {e}")
    
    return spectra


def find_filter_calibrations(cycle_start: datetime, filtercal_dir: Path, max_time_diff_seconds: int = 300) -> Dict[str, Optional[SpectrumData]]:
    """Find matching filter calibration files for a cycle.
    
    Args:
        cycle_start: Start time of the cycle
        filtercal_dir: Directory containing filter calibration files
        max_time_diff_seconds: Maximum time difference to consider a match
    
    Returns:
        Dict with '+5dBm' and '-4dBm' keys pointing to SpectrumData objects or None
    """
    if not filtercal_dir or not filtercal_dir.exists():
        return {'+5dBm': None, '-4dBm': None}
    
    closest = {'+5dBm': None, '-4dBm': None}
    min_diff = {'+5dBm': float('inf'), '-4dBm': float('inf')}
    
    # Find all filter calibration FITS files
    for fc_file in filtercal_dir.glob('*_*_*.fits'):
        try:
            # Parse filename: MMDDYYYY_HHMMSS_[+5dBm or -4dBm].fits
            parts = fc_file.stem.split('_')
            if len(parts) < 3:
                continue
            
            power = parts[2]  # '+5dBm' or '-4dBm'
            if power not in ['+5dBm', '-4dBm']:
                continue
            
            # Parse timestamp
            date_str = parts[0]  # MMDDYYYY
            time_str = parts[1]  # HHMMSS
            
            timestamp_str = f"{date_str}_{time_str}"
            fc_time = CycleDetector.parse_timestamp(timestamp_str)
            
            time_diff = abs((fc_time - cycle_start).total_seconds())
            
            if time_diff < min_diff[power] and time_diff <= max_time_diff_seconds:
                min_diff[power] = time_diff
                closest[power] = fc_file
        except Exception as e:
            continue
    
    # Load the closest filter calibration files
    result = {}
    for power, fc_file in closest.items():
        if fc_file:
            try:
                fc_spectrum = SpectrumData(fc_file).load()
                result[power] = fc_spectrum
            except Exception as e:
                print(f"    Warning: Could not load {fc_file.name}: {e}")
                result[power] = None
        else:
            result[power] = None
    
    return result


def get_next_day_directory(current_dir: Path) -> Optional[Path]:
    """Find the next day's directory based on naming pattern (e.g., 11042025 -> 11052025)."""
    # Parse current directory name (MMDDYYYY format)
    dir_name = current_dir.name
    try:
        # Try parsing as MMDDYYYY
        month = int(dir_name[:2])
        day = int(dir_name[2:4])
        year = int(dir_name[4:8])
        
        from datetime import datetime, timedelta
        current_date = datetime(year, month, day)
        next_date = current_date + timedelta(days=1)
        
        next_dir_name = next_date.strftime('%m%d%Y')
        next_dir = current_dir.parent / next_dir_name
        
        if next_dir.exists():
            return next_dir
    except (ValueError, IndexError):
        pass
    
    return None


def consolidate_directory(input_dir: Path, output_base: Path, filtercal_dir: Path = None, dry_run: bool = False):
    """Consolidate all FITS files in a directory.
    
    Automatically handles:
    - Boundary fixes: Removes spillover spectra from previous cycles
    - Multi-day cycles: Loads continuation data from next day's directory
    - Complete cycles: Stored in YYYYMMDD/cycle_NNN/ directories
    - Partial cycles: Stored in YYYYMMDD/partial_cycle_NNN/ with notes
    - Filter calibrations: Matches and processes filter calibration files
    
    Args:
        input_dir: Directory containing raw FITS files
        output_base: Base directory for consolidated output
        filtercal_dir: Directory containing filter calibration files (optional)
        dry_run: If True, analyze without writing files
    """
    
    print(f"\n{'='*60}")
    print(f"Consolidating: {input_dir}")
    print(f"Output: {output_base}")
    print(f"Auto-fixing boundaries and handling multi-day cycles...")
    print(f"{'='*60}\n")
    
    # Load spectra from current directory
    print(f"Loading spectra from {input_dir.name}...")
    spectra = load_spectra_from_directory(input_dir)
    
    if not spectra:
        print(f"No FITS files found in {input_dir}")
        return
        
    print(f"  Loaded {len(spectra)} spectra")
    
    # Check if next day's directory exists and load those spectra too
    next_day_dir = get_next_day_directory(input_dir)
    next_day_spectra = []
    if next_day_dir:
        print(f"Loading continuation data from {next_day_dir.name}...")
        next_day_spectra = load_spectra_from_directory(next_day_dir)
        print(f"  Loaded {len(next_day_spectra)} spectra from next day")
    
    # Combine all spectra for cycle detection
    all_spectra = spectra + next_day_spectra
    print(f"Total spectra for cycle detection: {len(all_spectra)}\n")
    
    # Combine all spectra for cycle detection
    all_spectra = spectra + next_day_spectra
    print(f"Total spectra for cycle detection: {len(all_spectra)}\n")
    
    # Group by cycles
    print("Detecting cycles...")
    cycles = CycleDetector.group_by_cycles(all_spectra)
    print(f"Found {len(cycles)} cycles\n")
    
    # Determine which cycles belong to the current day
    # (cycles that start within the current day's date range)
    current_day_date = None
    if spectra:
        first_timestamp = CycleDetector.parse_timestamp(spectra[0].timestamp)
        current_day_date = first_timestamp.date()
        print(f"Processing cycles for date: {current_day_date}\n")
    
    if dry_run:
        print(f"DRY RUN - No files will be written\n")
        complete_count = 0
        partial_count = 0
        
        for cycle_num, cycle_spectra in cycles.items():
            # Check initial start time to determine if this cycle belongs to current day
            initial_timestamps = [CycleDetector.parse_timestamp(s.timestamp) for s in cycle_spectra]
            initial_start_time = min(initial_timestamps)
            
            if current_day_date and initial_start_time.date() != current_day_date:
                continue  # Skip cycles from other days
            
            # Auto-fix boundaries
            original_count = len(cycle_spectra)
            if cycle_spectra and cycle_spectra[0].state != '2':
                first_state_2_idx = next((i for i, s in enumerate(cycle_spectra) if s.state == '2'), None)
                if first_state_2_idx and first_state_2_idx > 0:
                    cycle_spectra = cycle_spectra[first_state_2_idx:]
            
            # Recalculate timestamps after trimming
            timestamps = [CycleDetector.parse_timestamp(s.timestamp) for s in cycle_spectra]
            start_time = min(timestamps)  # This is now the correct start time (first state 2 spectrum)
            
            num_spectra = len(cycle_spectra)
            
            # Get state sequence
            states_seen = []
            for s in cycle_spectra:
                if len(states_seen) == 0 or s.state != states_seen[-1]:
                    states_seen.append(s.state)
            
            # Check if state sequence is correct
            expected_seq = ['2', '3', '4', '5', '6', '7', '1', '0', '1']
            has_correct_sequence = states_seen == expected_seq
            
            # Calculate time info
            end_time = max(timestamps)
            duration = (end_time - start_time).total_seconds() / 60.0
            
            # Categorize
            is_partial = False
            notes = []
            
            if original_count != num_spectra:
                notes.append(f"trimmed {original_count - num_spectra} spillover")
            
            if not has_correct_sequence:
                notes.append(f"seq: {','.join(states_seen)}")
                is_partial = True
            
            if start_time.date() != end_time.date():
                notes.append(f"spans to {end_time.date()}")
            
            if is_partial:
                partial_count += 1
                status = f" [PARTIAL: {'; '.join(notes)}]"
            else:
                complete_count += 1
                status = f" [{'; '.join(notes)}]" if notes else ""
            
            print(f"Cycle {cycle_num+1}: {num_spectra} spectra, {duration:.1f} min, {start_time.strftime('%Y-%m-%d %H:%M:%S')}{status}")
        
        print(f"\nSummary: {complete_count} complete cycles, {partial_count} partial cycles")
        print(f"All cycles will be processed and stored appropriately.")
        return
        return
    
    # Process each cycle
    for cycle_num, cycle_spectra in cycles.items():
        # Check initial start time to determine if this cycle belongs to current day
        initial_timestamps = [CycleDetector.parse_timestamp(s.timestamp) for s in cycle_spectra]
        initial_start_time = min(initial_timestamps)
        
        if current_day_date and initial_start_time.date() != current_day_date:
            continue  # Skip cycles from other days (they'll be processed when we run on that day)
        
        # Auto-fix boundaries - always remove spillover from previous cycle
        original_count = len(cycle_spectra)
        if cycle_spectra and cycle_spectra[0].state != '2':
            # Find first occurrence of state 2
            first_state_2_idx = next((i for i, s in enumerate(cycle_spectra) if s.state == '2'), None)
            if first_state_2_idx and first_state_2_idx > 0:
                removed_count = first_state_2_idx
                print(f"\nCycle {cycle_num+1}: Auto-trimmed {removed_count} spillover spectra")
                cycle_spectra = cycle_spectra[first_state_2_idx:]
        
        # Recalculate timestamps after trimming
        timestamps = [CycleDetector.parse_timestamp(s.timestamp) for s in cycle_spectra]
        start_time = min(timestamps)  # This is now the correct start time (first state 2 spectrum)
        
        num_spectra = len(cycle_spectra)
        
        # Get state sequence
        states_seen = []
        for s in cycle_spectra:
            if len(states_seen) == 0 or s.state != states_seen[-1]:
                states_seen.append(s.state)
        
        # Check if state sequence is correct
        expected_seq = ['2', '3', '4', '5', '6', '7', '1', '0', '1']
        has_correct_sequence = states_seen == expected_seq
        
        # Determine if this is a partial cycle
        is_partial = False
        partial_reasons = []
        
        if not has_correct_sequence:
            partial_reasons.append(f"sequence: {','.join(states_seen)}")
            is_partial = True
            is_partial = True
        
        if original_count != num_spectra:
            partial_reasons.append(f"trimmed {original_count - num_spectra} spillover spectra")
        
        cycle_type = "partial" if is_partial else "complete"
        print(f"\nProcessing Cycle {cycle_num+1} ({num_spectra} spectra) - {cycle_type.upper()}")
        if partial_reasons:
            print(f"  Note: {'; '.join(partial_reasons)}")
        
        # Calculate time info
        end_time = max(timestamps)
        duration = (end_time - start_time).total_seconds() / 60.0
        
        # IMPORTANT: Use start date for directory organization
        # This ensures cycles that span midnight (e.g., 23:52 to 00:10)
        # are kept together in the day they started, not split across days
        date_dir = output_base / start_time.strftime('%Y%m%d')
        
        # Use different prefix for partial cycles
        if is_partial:
            cycle_id = f"partial_cycle_{cycle_num+1:03d}"
        else:
            cycle_id = f"cycle_{cycle_num+1:03d}"
        
        cycle_dirname = f"{cycle_id}_{start_time.strftime('%m%d%Y_%H%M%S')}"
        cycle_dir = date_dir / cycle_dirname
        
        # Note if cycle spans multiple days
        if start_time.date() != end_time.date():
            print(f"  Note: Cycle spans from {start_time.strftime('%Y-%m-%d %H:%M:%S')} to {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  All spectra stored in: {date_dir.name}/{cycle_dirname}")
            print(f"  (keeping cycle together based on start time)")
        
        # Group by state, but handle state '1' specially (OC vs sky)
        spectra_by_state = defaultdict(list)
        state_1_oc = []   # First state 1 (open circuit, after state 7, before state 0)
        state_1_sky = []  # Second state 1 (sky observing, after state 0)
        
        seen_state_0 = False
        for spectrum in cycle_spectra:
            if spectrum.state == '1':
                if not seen_state_0:
                    state_1_oc.append(spectrum)
                else:
                    state_1_sky.append(spectrum)
            else:
                spectra_by_state[spectrum.state].append(spectrum)
                if spectrum.state == '0':
                    seen_state_0 = True
        
        # Add state 1 groups if they exist
        if state_1_oc:
            spectra_by_state['1_OC'] = state_1_oc
        if state_1_sky:
            spectra_by_state['1'] = state_1_sky
            
        print(f"  States found: {sorted(spectra_by_state.keys())}")
        
        # Determine antenna based on cycle start time
        antenna_info = get_antenna_info(start_time)
        print(f"  Antenna: {antenna_info['antenna_id']} ({antenna_info['antenna_size']})")
        
        # Write state files
        writer = ConsolidatedWriter(cycle_dir)
        for state_key in sorted(spectra_by_state.keys()):
            state_spectra = spectra_by_state[state_key]
            writer.write_state_file(state_key, state_spectra, cycle_id, antenna_info)
        
        # Process filter calibrations if directory provided
        if filtercal_dir:
            filtercals = find_filter_calibrations(start_time, filtercal_dir)
            for power, fc_spectrum in filtercals.items():
                if fc_spectrum:
                    # Write filter calibration with same FITS structure
                    fc_state_key = f'filtercal_{power}'
                    writer.write_state_file(fc_state_key, [fc_spectrum], cycle_id, antenna_info)
                    print(f"  Matched {power} filter calibration")
            
        # Write metadata
        metadata_notes = {
            "is_partial": is_partial,
            "partial_reasons": partial_reasons if is_partial else [],
            "original_spectra_count": original_count,
            "final_spectra_count": num_spectra,
            "state_sequence": states_seen
        }
        writer.write_metadata(cycle_num, spectra_by_state, cycle_id, antenna_info, metadata_notes)
        
        # Calculate size reduction
        original_size = sum(f.stat().st_size for f in [s.file_path for s in cycle_spectra])
        consolidated_size = sum(f.stat().st_size for f in cycle_dir.glob("*.fits"))
        reduction = original_size / consolidated_size if consolidated_size > 0 else 0
        
        print(f"  Original: {original_size/1024:.1f} KB")
        print(f"  Consolidated: {consolidated_size/1024:.1f} KB")
        print(f"  Reduction: {reduction:.1f}×")


def main():
    parser = argparse.ArgumentParser(
        description='Consolidate filterbank data into image cube format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Consolidate all days in Bandpass directory
  %(prog)s /path/to/Data/LunarDryLake/2025Nov/filterbank/Bandpass
  
  # Consolidate single day
  %(prog)s /path/to/Data/LunarDryLake/2025Nov/filterbank/Bandpass/11042025
  
  # With filter calibrations
  %(prog)s --filtercal-dir /path/to/filtercalibrations /path/to/Bandpass
  
  # Dry run to preview cycles
  %(prog)s --dry-run /path/to/Bandpass
        """
    )
    
    parser.add_argument('input_dir', type=Path,
                       help='Directory containing FITS files or parent directory with date subdirectories')
    parser.add_argument('--output', type=Path, default=None,
                       help='Output base directory (default: input_dir/../Bandpass_consolidated)')
    parser.add_argument('--filtercal-dir', type=Path, default=None,
                       help='Directory containing filter calibration files (optional)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview cycles without writing files')
    
    args = parser.parse_args()
    
    # Validate input
    if not args.input_dir.exists():
        print(f"ERROR: Input directory not found: {args.input_dir}")
        sys.exit(1)
    
    # Check if input_dir contains date subdirectories (like 11012025, 11022025, etc.)
    # or if it's a single date directory with FITS files
    subdirs = [d for d in args.input_dir.iterdir() if d.is_dir() and d.name != 'Backup']
    fits_files = list(args.input_dir.glob('*.fits'))
    
    # Determine if this is a parent directory with multiple days
    is_parent_dir = len(subdirs) > 0 and len(fits_files) == 0
    
    if is_parent_dir:
        # Filter for directories that look like date directories (8 digits starting with 1)
        date_dirs = [d for d in subdirs if len(d.name) == 8 and d.name[0] == '1' and d.name.isdigit()]
        date_dirs.sort()  # Process in chronological order
        
        if not date_dirs:
            print(f"ERROR: No date directories found in {args.input_dir}")
            sys.exit(1)
        
        print(f"Found {len(date_dirs)} date directories to process:")
        for d in date_dirs:
            print(f"  - {d.name}")
        print()
        
        # Determine output directory
        if args.output:
            output_base = args.output
        else:
            output_base = args.input_dir / 'Bandpass_consolidated'
        
        # Process each date directory
        for i, date_dir in enumerate(date_dirs, 1):
            print(f"\n{'='*60}")
            print(f"Processing day {i}/{len(date_dirs)}: {date_dir.name}")
            print(f"{'='*60}\n")
            consolidate_directory(date_dir, output_base, args.filtercal_dir, args.dry_run)
    else:
        # Single directory with FITS files
        # Determine output directory
        if args.output:
            output_base = args.output
        else:
            output_base = args.input_dir.parent / 'Bandpass_consolidated'
        
        # Run consolidation
        consolidate_directory(args.input_dir, output_base, args.filtercal_dir, args.dry_run)
    
    print(f"\n{'='*60}")
    print("Consolidation complete!")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
