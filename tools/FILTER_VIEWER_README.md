# Filter Response Viewer

Tool to visualize filter responses from calibration FITS files with LO power correction.

## Location

`tools/view_filter_responses.py`

## Features

- **LO Power Correction**: Normalizes filter measurements by actual LO power vs frequency
- **S21 Path Corrections**: Optional de-embedding of path loss before filters
- **Multi-panel Visualization**: Shows LO power, all filter responses, and selected individual filters
- **Statistics**: Reports peak response, mean level, and bandwidth for each filter

## Usage

```bash
# Basic usage (uses -4dBm calibration by default)
python3 tools/view_filter_responses.py /path/to/Cycle_MMDDYYYY_###

# Use +5dBm calibration instead
python3 tools/view_filter_responses.py /path/to/cycle --power=+5dBm

# Apply S21 path corrections
python3 tools/view_filter_responses.py /path/to/cycle --apply-s21

# Hide LO power plot (only show filter responses)
python3 tools/view_filter_responses.py /path/to/cycle --no-lo-plot

# Custom S21 directory
python3 tools/view_filter_responses.py /path/to/cycle --apply-s21 --s21-dir=/path/to/s2p/files
```

## Output

The tool creates a plot with up to 3 panels:

1. **LO Power vs Frequency** (optional, shown by default)
   - Shows actual LO power across 900-960 MHz
   - Displays uncertainty band from calibration
   - Shows reference power used for normalization

2. **All Filter Responses Overlaid**
   - All 21 filters plotted together with color coding
   - Shows filter behavior across full LO sweep
   - Legend shows filter number and center frequency

3. **Selected Individual Filters**
   - Plots every 5th filter (1, 6, 11, 16, 21) for clarity
   - Larger markers and lines for readability

## Filter Response Calculation

The tool computes filter responses as:

```
Filter Response (dB) = Filter Output Power (dBm) - LO Input Power (dBm)
```

Where:
- **Filter Output Power**: Converted from ADC counts → voltage → power
- **LO Input Power**: From log detector measurements at each frequency
- **Optional S21 correction**: Removes path loss before filter

This gives you the **transmission through the filter** at each frequency, normalized for LO power variation.

## Statistics

For each filter, the tool reports:
- **Peak** response and frequency
- **Mean** response across sweep  
- **Bandwidth** (number of frequency points within 3 dB of peak)

## Example Output

```
Filter  1 (center 904.0 MHz):
  Peak:  28.45 dB @ 959.0 MHz
  Mean:  27.19 dB
  BW (points > -3dB): 280 freq points
```

## Files Generated

- `filter_responses_<cycle>_<power>.png` - Basic plot
- `filter_responses_<cycle>_<power>_with_S21.png` - With S21 corrections

## Dependencies

- numpy
- matplotlib
- astropy
- utilities.io_utils (log detector calibration, FITS loader, conversions)

## Related Tools

- `plot_lo_power_with_errors.py` - Plot LO power flatness with uncertainty
- `view_filter_responses.py` - This tool (filter responses)
- Data viewers in `src/viewers/` - Interactive Dash-based viewers
