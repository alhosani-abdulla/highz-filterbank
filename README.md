# High-Redshift 21-cm Filterbank Spectrometer

Multi-channel filterbank spectrometer system designed to detect the global 21-cm hydrogen line signal from the Cosmic Dawn and Epoch of Reionization. The system uses an array of cavity filters to simultaneously capture multiple frequency channels, enabling the detection of the cosmological 21-cm absorption trough signature.

## Repository Structure

```
highz-filterbank/
├── README.md           # This file
├── LICENSE             # MIT License
├── .gitignore          # Git ignore rules
├── docs/               # Documentation
│   ├── HARDWARE.md        # Hardware wiring and configuration
│   ├── DATA_FORMAT.md     # FITS file format specification
│   └── CYCLE_CONTROLLER.md # Automated cycle controller guide
├── bin/                # Compiled binaries
└── src/                # Source code
    ├── calibration/       # Calibration routines
    └── data_aquisition/   # Data acquisition modules
```

## Overview

The filterbank spectrometer runs on Raspberry Pi and provides:
- **Calibration routines** for filterbank channels
- **Data acquisition modules** for continuous spectrum monitoring  
- **Signal processing** for 21-cm global signal detection

The goal is to detect the 21-cm global signal and the Cosmic Dawn absorption feature in the cosmological hydrogen line spectrum from high-redshift epochs (z ~ 15-30).

## System Architecture

The system consists of:
- Multiple cavity filters creating parallel frequency channels
- Raspberry Pi for real-time data acquisition and control
- Calibration software for channel characterization
- Data processing pipeline for signal extraction

## Source Modules

### Calibration (`src/calibration/`)
Contains calibration routines for characterizing filterbank channels and system response.

**Files:**
- `calibCode_v2.c` - Channel calibration and characterization

### Data Acquisition (`src/data_aquisition/`)
Real-time data acquisition from the filterbank spectrometer.

**Files:**
- `continuous_acq.c` - Continuous data acquisition subroutine (renamed from `ADHAT_c_subroutine_NO_SOCKET.c`)

## Hardware Requirements

- Raspberry Pi 4
- Three Waveshare High-Precision AD HAT boards (ADS1263 ADCs)
- Custom filterbank hardware with 21 cavity filters
- Hardware modifications for multi-ADC addressing

**See [docs/HARDWARE.md](docs/HARDWARE.md) for detailed wiring, pin assignments, and configuration.**

## Installation

### Python Package Installation

This repository provides Python analysis tools that can be installed as a package.

#### Editable Install (for development)
```bash
# Clone the repository
git clone https://github.com/alhosani-abdulla/highz-filterbank.git
cd highz-filterbank

# Install in editable mode with dependencies
pip install -e .

# Or with optional dev tools
pip install -e ".[dev]"
```

#### Direct Git Install
```bash
# Install directly from GitHub
pip install git+https://github.com/alhosani-abdulla/highz-filterbank.git
```

#### Using the Package
After installation, import modules in Python:
```python
# Load FITS data
import highz_filterbank
from highz_filterbank import io_utils
state_data = io_utils.load_state_file("path/to/state_1.fits")
filtercal = io_utils.load_filtercal("path/to/filtercal_+5dBm.fits")

# Create plots
from highz_filterbank import plot_utils
fig = plot_utils.create_power_plot(frequencies, powers, filter_indices)
```

#### S21 Calibration Data Path
The package needs S21 correction files for calibration. Set the path:
```bash
# Option 1: Set environment variable
export HIGHZ_FILTERBANK_S21_DIR="/path/to/highz-filterbank/characterization/s_parameters"

# Option 2: Pass as CLI argument when running viewers
python -m viewers.live_viewer --s21-dir "/path/to/s_parameters"
```

### Hardware C Programs

The C acquisition programs require additional hardware dependencies.

#### Required Repositories
The C code depends on the `High-Precision_AD_HAT` driver library:
```bash
# Both repositories should be in the highz directory:
/home/peterson/highz/
├── highz-filterbank/         # This repository
└── High-Precision_AD_HAT/    # AD HAT driver (dependency)
```

#### Required Libraries
- **libpigpio** - Raspberry Pi GPIO control
- **libcfitsio** - FITS file format handling
- **libgpiod** - GPIO device interface
- Standard libraries: pthread, rt, math

Install on Raspberry Pi:
```bash
sudo apt-get update
sudo apt-get install libcfitsio-dev libgpiod-dev pigpio
```

## Building

This project uses a Makefile for easy compilation. The Makefile automatically locates the AD HAT driver in the parent `highz` directory.

### Quick Build

```bash
# Clone the repository
git clone https://github.com/alhosani-abdulla/highz-filterbank.git
cd highz-filterbank

# Ensure the AD HAT driver repository is also cloned in the parent highz directory
# cd ../
# git clone https://github.com/alhosani-abdulla/High-Precision_AD_HAT.git

# Build everything
make

# Or build individual targets:
make calib      # Build calibration program only
make acq        # Build data acquisition program only
make clean      # Remove compiled binaries
```

### Build Targets

- `make` or `make all` - Build both calibration and data acquisition programs
- `make calib` - Build calibration program (`src/calibration/calib`)
- `make acq` - Build data acquisition program (`src/data_aquisition/acq`)
- `make clean` - Remove compiled binaries

### Manual Compilation (if needed)

If you need to compile manually without the Makefile:

```bash
# Calibration program
gcc -o src/calibration/calib src/calibration/calibCode_v2.c \
    ../High-Precision_AD_HAT/c/lib/Driver/ADS1263.c \
    ../High-Precision_AD_HAT/c/lib/Config/DEV_Config.c \
    ../High-Precision_AD_HAT/c/lib/Config/RPI_sysfs_gpio.c \
    ../High-Precision_AD_HAT/c/lib/Config/dev_hardware_SPI.c \
    -I../High-Precision_AD_HAT/c/lib/Driver \
    -I../High-Precision_AD_HAT/c/lib/Config \
    -lgpiod -lcfitsio -lpigpio -lrt -lpthread -lm

# Data acquisition program
gcc -o src/data_aquisition/acq src/data_aquisition/continuous_acq.c \
    ../High-Precision_AD_HAT/c/lib/Driver/ADS1263.c \
    ../High-Precision_AD_HAT/c/lib/Config/DEV_Config.c \
    ../High-Precision_AD_HAT/c/lib/Config/RPI_sysfs_gpio.c \
    ../High-Precision_AD_HAT/c/lib/Config/dev_hardware_SPI.c \
    -I../High-Precision_AD_HAT/c/lib/Driver \
    -I../High-Precision_AD_HAT/c/lib/Config \
    -lgpiod -lcfitsio -lpigpio -lrt -lpthread -lm
```

## Usage

### Python Analysis Tools

After installing the package (`pip install -e .` or `pip install git+...`):

#### Interactive Viewers
```bash
# Live viewer (monitors ongoing acquisition)
python src/viewers/live_viewer.py --data-dir /path/to/Data --port 8051

# Data viewer (browse archived data)
python src/viewers/data_viewer.py --data-dir /path/to/Data --port 8050
```

Or run as installed modules:
```bash
# Viewer modules are installed as top-level modules in this repo layout
python -m viewers.live_viewer --data-dir /path/to/Data
python -m viewers.data_viewer --data-dir /path/to/Data
```

#### Scripting with the Package
```python
import numpy as np
from highz_filterbank import io_utils, plot_utils

# Load and calibrate spectrum
state_file = "Data/20260308/Cycle_001/state_1.fits"
spectrum = io_utils.load_state_file(state_file, spectrum_index=0)

# Build calibration from filtercal files
cycle_dir = "Data/20260308/Cycle_001"
calibration = io_utils.build_filter_detector_calibration(
    cycle_dir=cycle_dir,
    apply_s21=True,
    s21_dir="/path/to/s_parameters"
)

# Apply calibration
frequencies, powers, filter_indices, voltages = io_utils.apply_calibration_to_spectrum(
    spectrum['data'],
    spectrum['lo_frequencies'],
    calibration,
    return_voltages=True
)

# Create plots
fig = plot_utils.create_power_plot(frequencies, powers, filter_indices)
fig.show()
```

### Hardware Calibration and Acquisition

#### Calibration
```bash
# Run calibration (requires Raspberry Pi hardware)
./src/calibration/calib [options]
```

#### Data Acquisition
```bash
# Run data acquisition (requires Raspberry Pi hardware)
./src/data_aquisition/acq [options]
```

## Documentation

Comprehensive documentation is available in the [`docs/`](docs/) directory:

- **[HARDWARE.md](docs/HARDWARE.md)** - Hardware configuration, ADC HAT wiring, GPIO pin assignments, and testing procedures
- **[DATA_FORMAT.md](docs/DATA_FORMAT.md)** - Detailed specification of the FITS file format, DATA_CUBE structure, and data loading examples
- **[CYCLE_CONTROLLER.md](docs/CYCLE_CONTROLLER.md)** - Guide to the automated cycle controller for continuous operation

For quick reference, see the [docs README](docs/README.md).

## Scientific Background

The 21-cm line is produced by the hyperfine transition of neutral hydrogen. During the Cosmic Dawn, the first stars and galaxies formed, and their radiation coupled the 21-cm signal to the gas temperature, potentially creating an absorption feature against the Cosmic Microwave Background. Detecting this signal provides crucial information about the early universe and the formation of the first luminous objects.

## License

MIT License - see LICENSE file for details

## Contact

For questions or collaboration inquiries, please open an issue on GitHub.
