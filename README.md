# High-Redshift 21-cm Filterbank Spectrometer

Multi-channel filterbank spectrometer system designed to detect the global 21-cm hydrogen line signal from the Cosmic Dawn and Epoch of Reionization. The system uses an array of cavity filters to simultaneously capture multiple frequency channels, enabling the detection of the cosmological 21-cm absorption trough signature.

## Repository Structure

```
highz-filterbank/
├── README.md           # This file
├── LICENSE             # MIT License
├── .gitignore          # Git ignore rules
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
- `ADHAT_c_subroutine_NO_SOCKET.c` - Data acquisition subroutine

## Hardware Requirements

- Raspberry Pi (tested on Pi 3/4)
- Custom filterbank hardware with cavity filters
- ADC interface for signal digitization

## Installation

```bash
# Clone the repository
git clone https://github.com/alhosani-abdulla/highz-filterbank.git
cd highz-filterbank

# Compile calibration code
gcc -o src/calibration/calib src/calibration/calibCode_v2.c -lm

# Compile data acquisition
gcc -o src/data_aquisition/acq src/data_aquisition/ADHAT_c_subroutine_NO_SOCKET.c -lm
```

## Usage

### Calibration
```bash
cd src/calibration
./calib [options]
```

### Data Acquisition
```bash
cd src/data_aquisition
./acq [options]
```

## Scientific Background

The 21-cm line is produced by the hyperfine transition of neutral hydrogen. During the Cosmic Dawn, the first stars and galaxies formed, and their radiation coupled the 21-cm signal to the gas temperature, potentially creating an absorption feature against the Cosmic Microwave Background. Detecting this signal provides crucial information about the early universe and the formation of the first luminous objects.

## License

MIT License - see LICENSE file for details

## Contact

For questions or collaboration inquiries, please open an issue on GitHub.
