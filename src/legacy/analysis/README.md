# Filterbank Data Analysis

Statistical analysis tools for examining consolidated spectra, comparing against references, and detecting anomalies in filterbank spectrometer data.

## Overview

The analysis module provides:
- **Deviation Analysis**: Compare spectra to reference measurements
- **Statistical Metrics**: Calculate mean, standard deviation, correlation
- **Anomaly Detection**: Identify unusual or corrupted spectra
- **Quality Assessment**: Evaluate spectrum quality and consistency

## Usage

### Deviation Analysis

Compare spectra to a reference and calculate deviations:

```python
from filterbank.analysis import deviations

# Analyze deviations from reference
day_dir = Path("/path/to/consolidated/20251106")
reference_spectrum_path = Path("/path/to/reference/spectrum.fits")
output_dir = Path("./analysis")

deviations.analyze_day_deviations(
    day_dir,
    reference_spectrum_path,
    state='1',
    output_dir=output_dir,
    filter_num=None,  # None for all, or specific 0-20
    verbose=True
)
```

#### Command Line Usage

```bash
# Analyze deviations for state 1
python -m filterbank.analysis.deviations /path/to/20251106 \
    --reference /path/to/reference.fits \
    --state 1

# Analyze specific filter
python -m filterbank.analysis.deviations /path/to/20251106 \
    --reference /path/to/reference.fits \
    --state 1 \
    --filter 5

# Save analysis plots to output directory
python -m filterbank.analysis.deviations /path/to/20251106 \
    --reference /path/to/reference.fits \
    --state 1 \
    --output ./analysis_plots
```

#### Options

- `--reference FILE`: Path to reference spectrum FITS file
- `--state N`: State to analyze
- `--filter N`: Analyze specific filter (0-20)
- `--output DIR`: Save plots and statistics to directory
- `--verbose`: Print detailed analysis information

### Programmatic API

```python
from filterbank.analysis.deviations import (
    compare_to_reference,
    calculate_deviations,
    SpectrumDeviations
)

# Load spectrum data
from filterbank.visualization.waterfall import load_state_file

waterfall, metadata = load_state_file(state_file_path)

# Compare to reference
for i, spectrum in enumerate(waterfall.rf_frequencies):
    deviation_result = compare_to_reference(
        spectrum,
        waterfall.powers[i],
        reference_spectrum
    )
    
    if deviation_result['is_suspect']:
        print(f"Spectrum {i}: {deviation_result['reasons']}")
```

## Analysis Types

### Statistical Comparison

Compares test spectrum to reference across frequency:
- **Mean Deviation**: Average power difference
- **Std Deviation**: Consistency of difference across frequency
- **Max Deviation**: Largest individual power difference
- **Correlation**: Pattern similarity (0-1, where 1 is identical)

### Quality Metrics

Assesses spectrum quality based on:
- **Flat Noise Floor**: Low-power, low-variation regions (indicates sync problems)
- **Signal Presence**: Detectable signal above noise
- **Shape Consistency**: Agreement with expected spectral shape
- **Outliers**: Extreme values indicating corruption

### Deviation Categories

- **Good**: Matches reference, consistent shape, high correlation
- **Offset**: Systematic power shift, otherwise good
- **Degraded**: Shape mismatch, lower correlation, but usable
- **Suspect**: Significant anomalies (sync issues, corrupted data)

## Output

Analysis generates:
- **Histogram Plots**: Distribution of deviations
- **Scatter Plots**: Deviation vs. frequency or cycle
- **Statistics CSV**: Summary metrics for each spectrum
- **Quality Report**: Flagged spectra with reasons

## Module Reference

### `deviations.py`
- `SpectrumDeviations`: Container for deviation analysis results
- `compare_to_reference()`: Compare single spectrum to reference
- `calculate_deviations()`: Batch analysis across multiple spectra
- `analyze_day_deviations()`: Full day analysis workflow
- `_check_spectrum_quality()`: Detailed quality assessment

## Quality Thresholds

Detection criteria for problematic spectra:

| Metric | Threshold | Meaning |
|--------|-----------|---------|
| Noise floor std dev | < 3 dB | Very flat (suspicious) |
| Noise floor power | < -45 dBm | Very low noise floor |
| Power difference | > 5 dB | Significantly below signal region |
| Correlation | < 0.82 | Poor pattern match |
| Mean offset | > 5.5 dB | Large systematic shift |
| Shape std dev | > 2.8 dB | Different spectral shape |

## Use Cases

### Day-by-Day Quality Assessment

```python
# Check all states for anomalies
for state in ['0', '1', '2', '3', '4', '5', '6', '7']:
    results = deviations.analyze_day_deviations(
        day_dir,
        reference_spectrum,
        state=state
    )
```

### Filter Performance Monitoring

```python
# Monitor specific filter across all states
for filter_num in range(21):
    results = deviations.analyze_day_deviations(
        day_dir,
        reference_spectrum,
        filter_num=filter_num
    )
```

### Correlation Analysis

Identify which spectra match known reference patterns:

```python
good_spectra = [i for i, result in enumerate(results) 
                if result['correlation'] > 0.85]
```

## Notes

- Reference spectrum should be from same day and state for best comparison
- Comparison requires overlapping frequency ranges
- Correlation values are normalized (0-1 scale)
- Large datasets benefit from per-filter analysis mode
- Quality thresholds can be customized via function parameters

## Troubleshooting

**No deviation detected?**
- Check reference spectrum path exists
- Verify frequency ranges overlap between test and reference
- Ensure same filter is being analyzed

**All spectra marked suspect?**
- Reference spectrum may be corrupted
- Check quality thresholds are appropriate
- Examine first few spectra manually

**Slow analysis?**
- Use per-filter mode to reduce data volume
- Analyze single state at a time
- Consider multiprocessing for batch analysis
