# Log Detector Calibration Utilities

Utilities for converting AD8318 log detector measurements to power and applying LO power corrections to filter calibration data.

## Location

`src/utilities/io_utils/log_detector.py`

## Overview

The log detector utilities provide:
- **Voltage to power conversion** using calibration curve interpolation
- **LO power vs frequency** loading from FITS files
- **Power correction functions** for normalizing filter measurements

## Classes

### `LogDetectorCalibration`

Manages log detector calibration and provides voltage-to-power conversion.

**Usage:**
```python
from utilities.io_utils import LogDetectorCalibration

# Load calibration (uses default calibration file)
calib = LogDetectorCalibration()

# Convert voltage to power
voltage = 0.536  # V (example log detector output)
power, is_interpolated = calib.voltage_to_power(voltage)
print(f"{voltage:.3f} V → {power:.2f} dBm")

# Convert ADC counts directly to power
adc_value = 1234567890  # example ADC reading
power, is_interpolated = calib.adc_to_power(adc_value)

# Show calibration info
calib.info()
```

**Output:**
```
Log Detector Calibration
  File: .../calibration_20260226.csv
  Valid voltage range: 0.5111 - 1.9948 V
  Valid power range: -63.0 - 11.0 dBm
  Calibration points: 75
```

### `LOPowerLoader`

Loads LO power vs frequency from filter calibration FITS files.

**Usage:**
```python
from utilities.io_utils import LOPowerLoader

# Load LO power data
lo_power = LOPowerLoader("filtercal_-4dBm.fits")

# Get power at specific frequency
power_at_930MHz = lo_power.get_power_at_frequency(930.0)  # MHz
print(f"LO power at 930 MHz: {power_at_930MHz:.2f} dBm")

# Get correction relative to mean
correction = lo_power.get_power_correction(930.0, reference='mean')
print(f"Correction: {correction:.2f} dB")

# Show info
lo_power.info()
```

**Output:**
```
LO Power Data from filtercal_-4dBm.fits
  Frequency range: 900.0 - 960.0 MHz
  Number of points: 301
  Mean power: -6.34 dBm
  Std dev: 0.57 dB
  Min power: -6.94 dBm @ 960.0 MHz
  Max power: 3.18 dBm @ 900.0 MHz
  Peak-to-peak: 10.12 dB
```

## Convenience Functions

### `load_lo_power()`

Quick function to load LO power data:

```python
from utilities.io_utils import load_lo_power

lo_power = load_lo_power("filtercal_-4dBm.fits")
power = lo_power.get_power_at_frequency(930.0)
```

### `get_lo_power_correction()`

**Recommended function** for filter calibration - returns a correction function:

```python
from utilities.io_utils import get_lo_power_correction

# Get correction function for a cycle
get_correction = get_lo_power_correction(
    cycle_dir="/path/to/Cycle_MMDDYYYY_###",
    power_setting='-4dBm',  # or '+5dBm'
    reference='mean'  # normalize to mean power
)

# Use it for each filter
for filter_num in range(21):
    freq = filter_center_frequencies[filter_num]  # MHz
    correction = get_correction(freq)  # dB
    
    # Apply correction to normalize measurement
    normalized_power = measured_power_dBm - correction
```

## Filter Calibration Workflow

**Problem:** LO power varies with frequency (e.g., ±0.4 dB). When measuring filter responses, you need to account for this variation to get true S21 values.

**Solution:** Use log detector measurements to normalize filter outputs.

### Step-by-Step

1. **Load LO power correction function:**
   ```python
   from utilities.io_utils import get_lo_power_correction
   
   get_correction = get_lo_power_correction(
       cycle_dir="/media/peterson/INDURANCE/Data/MMDDYYYY/Cycle_MMDDYYYY_###",
       power_setting='-4dBm',
       reference='mean'
   )
   ```

2. **For each filter measurement:**
   ```python
   # Your existing filter measurement code
   filter_num = 5
   center_freq = 919.0  # MHz
   measured_power = measure_filter_output(filter_num)  # your function
   
   # Apply LO power correction
   lo_correction = get_correction(center_freq)
   normalized_power = measured_power - lo_correction
   
   # Now use normalized_power for S21 calculation
   s21_db = normalized_power - input_power_reference
   ```

3. **Result:** S21 values are independent of LO power variation

### Example: Complete Filter Calibration

```python
from utilities.io_utils import get_lo_power_correction
import numpy as np

# Setup
cycle_dir = "/media/peterson/INDURANCE/Data/03012026/Cycle_03012026_114"
get_correction = get_lo_power_correction(cycle_dir, power_setting='-4dBm')

# Filter center frequencies (example - replace with actual values)
filter_freqs = np.array([
    903, 907, 911, 915, 919, 923, 927, 931, 935, 939, 943,
    947, 951, 955, 959, 915.5, 919.5, 923.5, 927.5, 931.5, 935.5
])

# Measure each filter (example)
s21_values = []
for filt_num, freq in enumerate(filter_freqs):
    # Your measurement code here
    measured_power = measure_filter_power(filt_num)  # dBm
    
    # Apply LO correction
    correction = get_correction(freq)
    normalized_power = measured_power - correction
    
    # Calculate S21 (example assuming known input power)
    reference_input_power = -6.34  # dBm (mean from get_correction reference)
    s21_db = normalized_power - reference_input_power
    
    s21_values.append(s21_db)
    
    print(f"Filter {filt_num:2d} @ {freq:6.1f} MHz: "
          f"S21 = {s21_db:6.2f} dB (corrected {correction:+.2f} dB)")

# Save results
s21_values = np.array(s21_values)
```

## Technical Details

### Calibration Curve Interpolation

- Uses **cubic interpolation** on the monotonic region of the AD8318 response
- Valid range: **-63 to +11 dBm** input power
- The detector saturates above ~11 dBm (voltage becomes non-monotonic)
- Below detection threshold (<-63 dBm), extrapolation is used (less accurate)

### Why Not Assume Flat Power?

The `-4dBm` LO setting shows **0.57 dB standard deviation** across 900-960 MHz:
- At 900 MHz: +3.18 dBm (9.5 dB higher than mean!)
- At 930 MHz: -6.37 dBm (near mean)
- At 960 MHz: -6.94 dBm (0.6 dB below mean)

**Without correction:** Your filter S21 measurements would have a ±0.5 dB systematic error just from LO power variation.

**With correction:** Measurements are normalized, giving true filter response independent of LO flatness.

### Which Power Setting to Use?

- **-4 dBm setting:** More consistent (0.75 dB peak-to-peak, excluding first point)
- **+5 dBm setting:** More variation (2.94 dB peak-to-peak)

**Recommendation:** Use `-4dBm` for better measurement accuracy.

## Files

- **Calibration:** `characterization/log_detector/calibration_20260226.csv`
- **Utilities:** `src/utilities/io_utils/log_detector.py`
- **Examples:** `example_log_detector_usage.py`
- **Legacy plot:** `plot_lo_power.py` (can be updated to use utilities)

## See Also

- `example_log_detector_usage.py` - Complete working examples
- `docs/CYCLE_CONTROLLER.md` - Automated cycle acquisition
- `characterization/log_detector/README.md` - Calibration procedure
