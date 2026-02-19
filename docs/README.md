# High-Z Filterbank Documentation

This directory contains documentation for the High-Z Filterbank data acquisition system.

## Documentation Files

### [DATA_FORMAT.md](DATA_FORMAT.md)
Detailed documentation of the FITS file format used by the system:
- File types (filter calibration, state data)
- DATA_CUBE structure and format
- Channel mapping and filter frequencies
- Code examples for loading and processing data
- Conversion to engineering units

### [CYCLE_CONTROLLER.md](CYCLE_CONTROLLER.md)
Documentation for the automated cycle controller:
- Usage and command-line parameters
- State sequence and execution
- Persistent state management
- Logging structure
- Configuration and troubleshooting

## Quick Links

**For Data Analysis:**
- Start with [DATA_FORMAT.md](DATA_FORMAT.md) to understand how data is stored
- See code examples for loading filtercal and state files
- Check filter center frequencies and channel mapping

**For System Operation:**
- See [CYCLE_CONTROLLER.md](CYCLE_CONTROLLER.md) for running the automated controller
- Configure antenna information in `/media/peterson/INDURANCE/Data/.antenna_config`
- Monitor logs in `/media/peterson/INDURANCE/Logs/run_*/`

## Additional Resources

- Source code: `/src/calibration/filterSweep.c`, `/src/data_aquisition/continuous_acq.c`
- Analysis tools: `Highz-EXP/src/filterbank/` (visualization and processing)
- Hardware setup: See main README.md
