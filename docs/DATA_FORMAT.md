# High-Z Filterbank Data Format Documentation

## Overview

The High-Z Filterbank system saves data in FITS (Flexible Image Transport System) format with a standardized structure. All data files use an image cube format where ADC measurements are packed into a DATA_CUBE column.

## File Types

### 1. Filter Calibration Files

**Naming:** `filtercal_+5dBm.fits`, `filtercal_-4dBm.fits`

**Purpose:** Calibration sweeps at two power levels for building power calibration curves.

**LO Sweep Range:** 900-960 MHz in 0.2 MHz steps (301 points)

**Structure:**
- **PRIMARY HDU Headers:**
  - `CYCLE_ID`: Cycle identifier (e.g., "Cycle_02182026_001")
  - `STATE`: Calibration state (e.g., "filtercal_+5dBm")
  - `TIMESTAMP`: Sweep timestamp (MMDDYYYY_HHMMSS)
  - `TIMEZONE`: Timezone offset (e.g., "-07:00")
  - `N_FILTERS`: Number of filter channels (21)
  - `N_LO_PTS`: Number of LO frequency points (301)
  - `N_SPECTRA`: Number of spectra in file (1)
  - `DATA_FMT`: Data format type ("image_cube")
  - `SYSVOLT`: System voltage (V)
  - `ADC_REFV`: ADC reference voltage (V) - typically 2.5V internal reference

- **Binary Table HDU (Extension 1):**
  - `DATA_CUBE`: 6321 values (301 freq × 21 channels), format: 6321K (32-bit unsigned int), units: ADC
  - `SPECTRUM_TIMESTAMP`: Timestamp string, format: 32A
  - `SPECTRUM_INDEX`: Spectrum index, format: J (32-bit int)
  - `SYSVOLT`: System voltage, format: D (64-bit float), units: V
  - `LO_FREQUENCIES`: 301 frequencies, format: 301D (64-bit float), units: MHz
  - `LOG_DETECTOR`: 301 values (one per frequency), format: 301K (32-bit unsigned int), units: ADC
    - Log detector output measuring LO power at each frequency point
    - Read from channel 7 of ADHAT2 (middle ADC)
  - `ADC_REFVOLT`: ADC reference voltage, format: D (64-bit float), units: V
    - Same value as ADC_REFV in PRIMARY HDU, stored for convenience

### 2. State Data Files

**Naming:** `state_0.fits`, `state_1.fits`, `state_2.fits`, ..., `state_7.fits`

**Purpose:** Continuous data acquisition for each switch state.

**LO Sweep Range:** 650-936 MHz in 2 MHz steps (144 points)

**Structure:**
- **PRIMARY HDU Headers:**
  - `CYCLE_ID`: Cycle identifier
  - `STATE`: Switch state number (0-7)
  - `N_FILTERS`: Number of filter channels (21)
  - `N_LO_PTS`: Number of LO frequency points (144)
  - `N_SPECTRA`: Number of spectra in file (varies)
  - `DATA_FMT`: Data format type ("image_cube")
  - `SYSVOLT`: System voltage (V)
  - `TIMEZONE`: Timezone offset

- **Binary Table HDU (Extension 1):**
  - Each row represents one spectrum measurement
  - `DATA_CUBE`: 3024 values (144 freq × 21 channels), format: 3024J (32-bit unsigned int), units: ADC
  - `SPECTRUM_TIMESTAMP`: Timestamp string, format: 25A
  - `SPECTRUM_INDEX`: Spectrum index, format: 1J
  - `SYSVOLT`: System voltage, format: 1E (32-bit float), units: volts
  - `LO_FREQUENCIES`: 144 frequencies, format: 144E (32-bit float), units: MHz

## DATA_CUBE Format

The DATA_CUBE is the core data structure containing all ADC measurements.

### Storage Format

**Flat 1D Array:** All measurements are stored sequentially in a single 1D array.

**Packing Order:** For each LO frequency point, all 21 filter channels are written consecutively.

```
[freq_0_chan_0, freq_0_chan_1, ..., freq_0_chan_20,
 freq_1_chan_0, freq_1_chan_1, ..., freq_1_chan_20,
 ...
 freq_N_chan_0, freq_N_chan_1, ..., freq_N_chan_20]
```

### Reshaping for Analysis

To work with the data, reshape the 1D array to 2D:

**Filter Calibration Files:**
```python
data_cube = hdul[1].data['DATA_CUBE'][0]  # Shape: (6321,)
data_reshaped = data_cube.reshape(301, 21)  # Shape: (301 frequencies, 21 channels)
```

**State Files:**
```python
# Multiple spectra - loop through rows
for spec_idx in range(len(hdul[1].data)):
    data_cube = hdul[1].data['DATA_CUBE'][spec_idx]  # Shape: (3024,)
    data_reshaped = data_cube.reshape(144, 21)  # Shape: (144 frequencies, 21 channels)
```

### Channel Mapping

The 21 channels correspond to 3 AD HATs with 7 channels each:

- **Channels 0-6:** ADHAT_1 (channels 0-6)
- **Channels 7-13:** ADHAT_2 (channels 0-6)
- **Channels 14-20:** ADHAT_3 (channels 0-6)

### Filter Center Frequencies

The 21 filter channels have center frequencies spaced 2.6 MHz apart:

```python
filter_centers = [904.0 + i * 2.6 for i in range(21)]
# [904.0, 906.6, 909.2, 911.8, 914.4, 917.0, 919.6, 922.2, 924.8,
#  927.4, 930.0, 932.6, 935.2, 937.8, 940.4, 943.0, 945.6, 948.2,
#  950.8, 953.4, 956.0]  # MHz
```

### Log Detector (Filter Calibration Only)

The log detector (Analog Devices AD8318) measures the Local Oscillator power at each frequency during calibration sweeps:

- **Location:** Channel 7 of ADHAT2 (middle ADC, CS pin 22)
- **Purpose:** Track LO power variations across the sweep for accurate calibration
- **Data:** 301 ADC readings (one per frequency) stored in `LOG_DETECTOR` column
- **Usage:** Correct for LO power flatness variations when building power calibration curves
- **Integration:** Combined with S21 measurements to achieve absolute power calibration

The log detector is only active during filter calibration sweeps (`filtercal_+5dBm.fits` and `filtercal_-4dBm.fits`). State acquisition files do not include log detector data.

## Data Access Example

### Loading Filter Calibration Data

```python
from astropy.io import fits
import numpy as np

# Open filtercal file
hdul = fits.open('filtercal_+5dBm.fits')

# Get metadata
cycle_id = hdul[0].header['CYCLE_ID']
n_filters = hdul[0].header['N_FILTERS']
n_lo_pts = hdul[0].header['N_LO_PTS']
adc_refv = hdul[0].header['ADC_REFV']  # ADC reference voltage

# Get data
data_cube = hdul[1].data['DATA_CUBE'][0]
lo_frequencies = hdul[1].data['LO_FREQUENCIES'][0]
log_detector = hdul[1].data['LOG_DETECTOR'][0]  # LO power measurements

# Reshape to 2D: (301 frequencies × 21 channels)
data_2d = data_cube.reshape(n_lo_pts, n_filters)

# Access specific filter channel at specific frequency
freq_idx = 20  # Index for ~904 MHz
filter_chan = 0  # First filter
adc_value = data_2d[freq_idx, filter_chan]

# Access log detector reading at same frequency
log_det_adc = log_detector[freq_idx]

# Convert to voltage (example for bipolar ADC)
def adc_to_voltage(adc_value, ref_voltage=2.5):
    if (adc_value >> 31) == 1:  # Negative value
        return ref_voltage * 2 - (adc_value / 2147483648.0) * ref_voltage
    else:
        return (adc_value / 2147483647.8) * ref_voltage

filter_voltage = adc_to_voltage(adc_value, adc_refv)
log_det_voltage = adc_to_voltage(log_det_adc, adc_refv)

hdul.close()
```

### Loading State Data

```python
from astropy.io import fits
import numpy as np

# Open state file
hdul = fits.open('state_1.fits')

# Get number of spectra
n_spectra = len(hdul[1].data)
n_filters = hdul[0].header['N_FILTERS']
n_lo_pts = hdul[0].header['N_LO_PTS']

# Process each spectrum
for spec_idx in range(n_spectra):
    # Get metadata for this spectrum
    timestamp = hdul[1].data['SPECTRUM_TIMESTAMP'][spec_idx]
    lo_frequencies = hdul[1].data['LO_FREQUENCIES'][spec_idx]
    
    # Get ADC data
    data_cube = hdul[1].data['DATA_CUBE'][spec_idx]
    
    # Reshape to 2D: (144 frequencies × 21 channels)
    data_2d = data_cube.reshape(n_lo_pts, n_filters)
    
    # Process this spectrum...
    print(f"Spectrum {spec_idx}: {timestamp}")

hdul.close()
```

## Directory Structure

```
/media/peterson/INDURANCE/Data/
├── MMDDYYYY/                          # Date directory
│   ├── Cycle_MMDDYYYY_001/           # Cycle directory
│   │   ├── cycle_metadata.json       # Cycle metadata
│   │   ├── filtercal_+5dBm.fits     # High power calibration
│   │   ├── filtercal_-4dBm.fits     # Low power calibration
│   │   ├── state_0.fits             # State 0 data
│   │   ├── state_1.fits             # State 1 data
│   │   ├── state_2.fits             # State 2 data
│   │   ├── state_3.fits             # State 3 data
│   │   ├── state_4.fits             # State 4 data
│   │   ├── state_5.fits             # State 5 data
│   │   ├── state_6.fits             # State 6 data
│   │   └── state_7.fits             # State 7 data
│   └── Cycle_MMDDYYYY_002/
│       └── ...
└── .cycle_state                       # Persistent state tracking
```

## Conversion to Engineering Units

### ADC to Voltage

ADC values need to be converted to voltage using the AD HAT specifications. The ADS1263 uses a 32-bit bipolar ADC with the conversion formula:

```python
def adc_to_voltage(adc_value, ref_voltage=2.5):
    """Convert 32-bit bipolar ADC reading to voltage
    
    Args:
        adc_value: 32-bit unsigned integer ADC reading
        ref_voltage: ADC reference voltage (default 2.5V)
    
    Returns:
        voltage in volts
    """
    if (adc_value >> 31) == 1:  # Negative value (MSB set)
        return ref_voltage * 2 - (adc_value / 2147483648.0) * ref_voltage
    else:
        return (adc_value / 2147483647.8) * ref_voltage
```

The ADC reference voltage (`ADC_REFV`) is stored in the FITS header and typically 2.5V (internal reference).

### Voltage to Power (dBm)

Power calibration curves are built from the filtercal files by:
1. Finding the row closest to each filter center frequency
2. Reading the ADC values at low and high power levels
3. Converting ADC → voltage → dBm using known power levels
4. Building a linear calibration: `power_dBm = slope * voltage + intercept`
5. Using log detector data to correct for LO power variations
6. Applying S21 corrections from VNA measurements to get absolute power

See `filter_plotting.py` utilities for reference implementations.

## Source Code References

- **Filter Calibration:** `/src/instrument/filterSweep.c`
  - Lines 267-277: Log detector reading in COLLECT_ADC_DATA()
  - Lines 518-526: DATA_CUBE packing for filtercal (301×21)
  - Lines 576-584: LOG_DETECTOR column packing (301 values)
  
- **Continuous Acquisition:** `/src/instrument/continuous_acq.c`
  - DATA_CUBE packing for state files (144×21)
  - Note: State files do not include LOG_DETECTOR data

- **Common Hardware Configuration:** `/src/instrument/highz_common.h`
  - ADC pin definitions and hardware constants
  - Log detector configuration (channel 7, ADHAT2)

## Notes

- All ADC values are stored as unsigned 32-bit integers
- LO frequencies are stored as 32-bit or 64-bit floats in MHz
- System voltage is monitored and stored with each measurement
- Timestamps use format MMDDYYYY_HHMMSS with configurable timezone offset
