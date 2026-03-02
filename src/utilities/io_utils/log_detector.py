"""
Log Detector Calibration Utilities

Provides functions for converting AD8318 log detector measurements to power
and loading LO power vs frequency data from calibration FITS files.
"""

import numpy as np
from scipy.interpolate import interp1d
from pathlib import Path
from astropy.io import fits

from .conversions import adc_counts_to_voltage


# Default paths - can be overridden
DEFAULT_CALIBRATION_FILE = '/home/peterson/highz/highz-filterbank/characterization/log_detector/calibration_20260226.csv'
ADC_REFERENCE_VOLTAGE = 2.5  # V (log detector ADC reference)


class LogDetectorCalibration:
    """
    Log detector calibration manager for AD8318 detector.
    
    Loads calibration curve and provides voltage-to-power conversion using
    interpolation over the monotonic (valid) region of the detector response.
    
    Parameters
    ----------
    calibration_file : str or Path, optional
        Path to calibration CSV file. If None, uses default.
    
    Attributes
    ----------
    interp_func : callable
        Interpolation function: voltage (V) -> power (dBm)
    v_min, v_max : float
        Valid voltage range for interpolation (V)
    powers : ndarray
        Calibration power levels (dBm)
    voltages : ndarray
        Calibration voltages (V)
    """
    
    def __init__(self, calibration_file=None):
        if calibration_file is None:
            calibration_file = DEFAULT_CALIBRATION_FILE
        
        self.calibration_file = Path(calibration_file)
        self._load_calibration()
    
    def _load_calibration(self):
        """Load calibration data and create interpolator for monotonic region."""
        # Load calibration CSV
        calib = np.genfromtxt(self.calibration_file, delimiter=',', skip_header=7,
                              names=['Power_dBm', 'Voltage_V', 'Std_Dev_V', 'N_Samples'])
        
        # Find monotonic region where detector is working (not noise floor, not saturated)
        # Start from -70 dBm or where voltage < 2.0 V (detector starts working reliably)
        start_idx = np.where(calib['Voltage_V'] < 2.0)[0][0]
        
        # Find where voltage stops decreasing monotonically (detector saturates)
        voltage_diff = np.diff(calib['Voltage_V'][start_idx:])
        non_monotonic = np.where(voltage_diff >= 0)[0]
        
        if len(non_monotonic) > 0:
            # Use data up to first non-monotonic point
            end_idx = start_idx + non_monotonic[0] + 1
        else:
            # All data from start is monotonic
            end_idx = len(calib['Power_dBm'])
        
        # Extract monotonic portion
        self.voltages = calib['Voltage_V'][start_idx:end_idx]
        self.powers = calib['Power_dBm'][start_idx:end_idx]
        self.std_devs = calib['Std_Dev_V'][start_idx:end_idx]
        
        # Store valid range
        self.v_min = self.voltages.min()
        self.v_max = self.voltages.max()
        self.p_min = self.powers.min()
        self.p_max = self.powers.max()
        
        # Create interpolator (voltage -> power)
        self.interp_func = interp1d(self.voltages, self.powers, kind='cubic',
                                   bounds_error=False, fill_value='extrapolate')
    
    def voltage_to_power(self, voltage):
        """
        Convert log detector voltage to power using calibration curve.
        
        Parameters
        ----------
        voltage : float or array-like
            Log detector output voltage(s) in volts
        
        Returns
        -------
        power : float or ndarray
            RF power in dBm
        is_interpolated : bool or ndarray
            Whether value was interpolated (True) or extrapolated (False)
        """
        voltage = np.atleast_1d(voltage)
        power = self.interp_func(voltage)
        is_interpolated = (voltage >= self.v_min) & (voltage <= self.v_max)
        
        if voltage.size == 1:
            return float(power[0]), bool(is_interpolated[0])
        return power, is_interpolated
    
    def estimate_power_uncertainty(self, voltage, voltage_uncertainty=None):
        """
        Estimate power uncertainty from voltage uncertainty using calibration.
        
        Uses linear interpolation of calibration standard deviations to estimate
        power uncertainty at a given voltage.
        
        Parameters
        ----------
        voltage : float or array-like
            Log detector voltage(s) in volts
        voltage_uncertainty : float or array-like, optional
            Voltage measurement uncertainty in volts. If None, uses calibration
            std devs only. If provided, adds in quadrature with calibration uncertainty.
        
        Returns
        -------
        power_uncertainty : float or ndarray
            Estimated power uncertainty in dB
        """
        voltage = np.atleast_1d(voltage)
        
        # Estimate dP/dV from calibration curve using finite differences
        # This gives the slope (sensitivity) at each voltage
        dv = 0.001  # Small voltage step (1 mV)
        v_plus = voltage + dv
        v_minus = voltage - dv
        p_plus = self.interp_func(v_plus)
        p_minus = self.interp_func(v_minus)
        dP_dV = (p_plus - p_minus) / (2 * dv)  # dB/V
        
        # Get calibration voltage uncertainty at this voltage (interpolate from cal data)
        v_std_interp = np.interp(voltage, self.voltages, self.std_devs)
        
        # Combine uncertainties if measurement uncertainty provided
        if voltage_uncertainty is not None:
            voltage_uncertainty = np.atleast_1d(voltage_uncertainty)
            total_v_uncertainty = np.sqrt(v_std_interp**2 + voltage_uncertainty**2)
        else:
            total_v_uncertainty = v_std_interp
        
        # Propagate voltage uncertainty to power uncertainty
        power_uncertainty = np.abs(dP_dV) * total_v_uncertainty
        
        if voltage.size == 1:
            return float(power_uncertainty[0])
        return power_uncertainty
    
    def adc_to_voltage(self, adc_value, vref=ADC_REFERENCE_VOLTAGE):
        """
        Convert ADC counts to voltage (bipolar mode).
        
        Parameters
        ----------
        adc_value : int or array-like
            ADC reading in counts
        vref : float, optional
            Reference voltage (default 2.5V)
        
        Returns
        -------
        float or ndarray
            Voltage in volts
        """
        # ADS1263 is 32-bit ADC in bipolar mode: range is -2^31 to +2^31-1
        # Voltage = (adc_value / 2^31) * Vref
        return (np.asarray(adc_value) / 2147483648.0) * vref
    
    def adc_to_power(self, adc_value, vref=ADC_REFERENCE_VOLTAGE):
        """
        Convert ADC counts directly to power in dBm.
        
        Parameters
        ----------
        adc_value : int or array-like
            ADC reading in counts
        vref : float, optional
            Reference voltage (default 2.5V)
        
        Returns
        -------
        power : float or ndarray
            RF power in dBm
        is_interpolated : bool or ndarray
            Whether value was interpolated (True) or extrapolated (False)
        """
        voltage = self.adc_to_voltage(adc_value, vref)
        return self.voltage_to_power(voltage)
    
    def info(self):
        """Print calibration information."""
        print(f"Log Detector Calibration")
        print(f"  File: {self.calibration_file}")
        print(f"  Valid voltage range: {self.v_min:.4f} - {self.v_max:.4f} V")
        print(f"  Valid power range: {self.p_min:.1f} - {self.p_max:.1f} dBm")
        print(f"  Calibration points: {len(self.voltages)}")


class LOPowerLoader:
    """
    Load and interpolate LO power vs frequency from calibration FITS files.
    
    This class loads log detector measurements from filter calibration files
    and provides LO power at any frequency via interpolation.
    
    Parameters
    ----------
    fits_file : str or Path
        Path to filtercal_+5dBm.fits or filtercal_-4dBm.fits file
    calibration : LogDetectorCalibration, optional
        Log detector calibration object. If None, creates default.
    
    Attributes
    ----------
    frequencies : ndarray
        LO frequencies in MHz
    voltages : ndarray
        Log detector voltages in V
    powers : ndarray
        LO power in dBm
    power_uncertainties : ndarray
        Power uncertainties in dB (1-sigma from calibration)
    """
    
    def __init__(self, fits_file, calibration=None):
        self.fits_file = Path(fits_file)
        
        if calibration is None:
            self.calibration = LogDetectorCalibration()
        else:
            self.calibration = calibration
        
        self._load_data()
    
    def _load_data(self):
        """Load log detector data from FITS file."""
        with fits.open(self.fits_file) as hdul:
            # Get data table
            data = hdul[1].data
            
            # Extract log detector ADC values (shape is (1, N))
            log_detector_adc = data['LOG_DETECTOR'][0]
            
            # Get frequencies from data table
            self.frequencies = data['LO_FREQUENCIES'][0]
            
            # Convert ADC → voltage → power
            self.voltages = self.calibration.adc_to_voltage(log_detector_adc)
            self.powers, self.is_interpolated = self.calibration.voltage_to_power(self.voltages)
            
            # Estimate power uncertainties from calibration
            self.power_uncertainties = self.calibration.estimate_power_uncertainty(self.voltages)
    
    def get_power_at_frequency(self, freq):
        """
        Get LO power at specific frequency via interpolation.
        
        Parameters
        ----------
        freq : float or array-like
            Frequency or frequencies in MHz
        
        Returns
        -------
        power : float or ndarray
            LO power in dBm at requested frequency/frequencies
        """
        freq = np.atleast_1d(freq)
        
        # Interpolate power vs frequency
        power_interp = np.interp(freq, self.frequencies, self.powers)
        
        if freq.size == 1:
            return float(power_interp[0])
        return power_interp
    
    def get_power_correction(self, freq, reference='mean'):
        """
        Get power correction factor relative to reference.
        
        Useful for normalizing measurements when LO power varies with frequency.
        
        Parameters
        ----------
        freq : float or array-like
            Frequency or frequencies in MHz
        reference : float or 'mean' or 'median', optional
            Reference power level. If 'mean' or 'median', uses that statistic
            of the loaded power data. Otherwise uses specified value in dBm.
        
        Returns
        -------
        correction : float or ndarray
            Power correction in dB (measured_power - reference_power)
            Subtract this from measurements to normalize to reference level.
        """
        power_at_freq = self.get_power_at_frequency(freq)
        
        if reference == 'mean':
            ref_power = np.mean(self.powers)
        elif reference == 'median':
            ref_power = np.median(self.powers)
        else:
            ref_power = float(reference)
        
        # Correction = measured - reference
        # To normalize: measured_dBm - correction = reference level
        return power_at_freq - ref_power
    
    def info(self):
        """Print LO power information."""
        print(f"LO Power Data from {self.fits_file.name}")
        print(f"  Frequency range: {self.frequencies[0]:.1f} - {self.frequencies[-1]:.1f} MHz")
        print(f"  Number of points: {len(self.frequencies)}")
        print(f"  Mean power: {np.mean(self.powers):.2f} dBm")
        print(f"  Std dev: {np.std(self.powers):.2f} dB")
        print(f"  Min power: {np.min(self.powers):.2f} dBm @ {self.frequencies[np.argmin(self.powers)]:.1f} MHz")
        print(f"  Max power: {np.max(self.powers):.2f} dBm @ {self.frequencies[np.argmax(self.powers)]:.1f} MHz")
        print(f"  Peak-to-peak: {np.ptp(self.powers):.2f} dB")
        print(f"  Mean uncertainty: {np.mean(self.power_uncertainties):.3f} dB (1-sigma)")
        print(f"  Max uncertainty: {np.max(self.power_uncertainties):.3f} dB")


class FilterDetectorCalibration:
    """
    Linear calibration for filter log detectors using two-point method.
    
    Each of the 21 filter outputs connects to an AD8318 log detector with a 
    slightly different transfer function. Rather than fully characterizing all 
    21 detectors, we use a two-point linear calibration from the filtercal 
    measurements at two different LO power settings (+5dBm and -4dBm).
    
    The actual input power at each setting is determined using the LO log 
    detector (which has a full calibration curve). This gives us two points 
    on each filter detector's transfer function, which we use to fit a linear 
    relationship in the operating region.
    
    Parameters
    ----------
    cycle_dir : str or Path
        Path to cycle directory containing filtercal_+5dBm.fits and 
        filtercal_-4dBm.fits files
    lo_calibration : LogDetectorCalibration, optional
        LO detector calibration object. If None, creates default.
    detector_noise_floor_dbm : float, optional
        Minimum power the AD8318 detector can measure. Values below this
        are clipped (default: -65 dBm).
    apply_s21 : bool, optional
        If True, apply S21 path corrections to LO powers during calibration.
        This calibrates the detector against actual detector input power
        (after cables/splitters/filters) instead of LO output power.
        Default: False.
    s21_dir : str or Path, optional
        Directory containing filter S21 .s2p files. If None and apply_s21=True,
        uses default location in characterization/s_parameters/.
    
    Attributes
    ----------
    n_filters : int
        Number of filters (typically 21)
    ref_voltage : float
        ADC reference voltage in volts (read from FITS file)
    detector_noise_floor_dbm : float
        Minimum detectable power (clips extrapolation below this)
    apply_s21 : bool
        Whether S21 corrections were applied during calibration
    slopes : ndarray
        Linear calibration slopes (dBm/V) for each filter, shape (n_filters,)
    intercepts : ndarray
        Linear calibration intercepts (dBm) for each filter, shape (n_filters,)
    frequencies : ndarray
        LO frequencies in MHz
    powers_low : ndarray
        Reference power at each filter for -4dBm setting, shape (n_filters,)
        (LO output power if apply_s21=False, detector input power if apply_s21=True)
    powers_high : ndarray
        Reference power at each filter for +5dBm setting, shape (n_filters,)
        (LO output power if apply_s21=False, detector input power if apply_s21=True)
    voltages_low : ndarray
        Mean voltage at each filter for -4dBm setting, shape (n_filters,)
    voltages_high : ndarray
        Mean voltage at each filter for +5dBm setting, shape (n_filters,)
    """
    
    def __init__(self, cycle_dir, lo_calibration=None, detector_noise_floor_dbm=-65.0,
                 apply_s21=False, s21_dir=None):
        self.cycle_dir = Path(cycle_dir)
        self.detector_noise_floor_dbm = detector_noise_floor_dbm
        self.apply_s21 = apply_s21
        
        if lo_calibration is None:
            self.lo_calibration = LogDetectorCalibration()
        else:
            self.lo_calibration = lo_calibration
        
        # Set S21 directory
        if s21_dir is None and apply_s21:
            # Use default location (go up from src/utilities/io_utils/ to repo root)
            self.s21_dir = Path(__file__).parent.parent.parent.parent / "characterization" / "s_parameters" / "filter_s21_20260226"
        else:
            self.s21_dir = Path(s21_dir) if s21_dir is not None else None
        
        self._load_and_calibrate()
    
    def _load_and_calibrate(self):
        """Load both filtercal files and compute linear calibrations."""
        # Load both power settings
        fits_low = self.cycle_dir / "filtercal_-4dBm.fits"
        fits_high = self.cycle_dir / "filtercal_+5dBm.fits"
        
        if not fits_low.exists():
            raise FileNotFoundError(f"Low power calibration not found: {fits_low}")
        if not fits_high.exists():
            raise FileNotFoundError(f"High power calibration not found: {fits_high}")
        
        # Load LO power measurements using LOPowerLoader
        lo_loader_low = LOPowerLoader(fits_low, self.lo_calibration)
        lo_loader_high = LOPowerLoader(fits_high, self.lo_calibration)
        
        # Store frequencies (should be same for both)
        self.frequencies = lo_loader_low.frequencies
        
        # Load filter ADC data and reference voltage
        with fits.open(fits_low) as hdul:
            data_cube_low = hdul[1].data['DATA_CUBE'].flatten()
            n_lo_pts = hdul[0].header['N_LO_PTS']
            n_filters = hdul[0].header['N_FILTERS']
            filter_adc_low = data_cube_low.reshape(n_lo_pts, n_filters)
            # Get ADC reference voltage from FITS file
            self.ref_voltage = float(hdul[1].data['ADC_REFVOLT'][0])
        
        with fits.open(fits_high) as hdul:
            data_cube_high = hdul[1].data['DATA_CUBE'].flatten()
            filter_adc_high = data_cube_high.reshape(n_lo_pts, n_filters)
        
        self.n_filters = n_filters
        
        # Convert ADC to voltage for filters using same method as viewer
        filter_voltages_low = adc_counts_to_voltage(filter_adc_low, ref=self.ref_voltage, mode='c_like')
        filter_voltages_high = adc_counts_to_voltage(filter_adc_high, ref=self.ref_voltage, mode='c_like')
        
        # Get filter center frequencies (904.0, 906.6, 909.2, ... 956.0 MHz)
        filter_centers = 904.0 + np.arange(n_filters) * 2.6  # MHz
        
        # Load S21 corrections if requested
        s21_data = None
        if self.apply_s21:
            if self.s21_dir.exists():
                try:
                    # Import locally to avoid circular dependency
                    from .calibration import load_s21_corrections
                    s21_data = load_s21_corrections(self.s21_dir)
                    print(f"Loaded S21 corrections for {len(s21_data)} filters from {self.s21_dir.name}")
                except Exception as e:
                    print(f"Warning: Could not load S21 corrections: {e}")
                    print("Continuing with LO output power (no S21 correction)")
                    self.apply_s21 = False
            else:
                print(f"Warning: S21 directory not found: {self.s21_dir}")
                print("Continuing with LO output power (no S21 correction)")
                self.apply_s21 = False
        
        # For each filter, find the frequency index closest to its center
        # and extract voltage and power at that frequency
        self.voltages_low = np.zeros(n_filters)
        self.voltages_high = np.zeros(n_filters)
        self.powers_low = np.zeros(n_filters)
        self.powers_high = np.zeros(n_filters)
        
        for filt_num in range(n_filters):
            center_freq = filter_centers[filt_num]
            
            # Find closest frequency point
            freq_idx = np.argmin(np.abs(self.frequencies - center_freq))
            
            # Extract voltage at that frequency
            self.voltages_low[filt_num] = filter_voltages_low[freq_idx, filt_num]
            self.voltages_high[filt_num] = filter_voltages_high[freq_idx, filt_num]
            
            # Extract LO output power at that frequency
            lo_power_low = lo_loader_low.powers[freq_idx]
            lo_power_high = lo_loader_high.powers[freq_idx]
            
            # Apply S21 correction if available (converts LO output power to detector input power)
            if self.apply_s21 and s21_data is not None and (filt_num + 1) in s21_data:
                s21_freqs = s21_data[filt_num + 1]['freqs']
                s21_db = s21_data[filt_num + 1]['s21_db']
                
                # Interpolate S21 at center frequency
                s21_at_center = np.interp(center_freq, s21_freqs, s21_db)
                
                # Apply S21: P_detector_input = P_LO_output + S21_dB (S21 is negative for loss)
                self.powers_low[filt_num] = lo_power_low + s21_at_center
                self.powers_high[filt_num] = lo_power_high + s21_at_center
            else:
                # Use LO output power directly (no S21 correction)
                self.powers_low[filt_num] = lo_power_low
                self.powers_high[filt_num] = lo_power_high
        
        # Compute linear fit for each filter: P = slope * V + intercept
        # Two points: (V_low, P_low) and (V_high, P_high) at filter's center frequency
        dV = self.voltages_high - self.voltages_low
        dP = self.powers_high - self.powers_low
        
        self.slopes = dP / dV  # dBm/V, shape: (n_filters,)
        self.intercepts = self.powers_low - self.slopes * self.voltages_low  # dBm
        
        # Check for problematic calibrations
        if np.any(np.abs(dV) < 0.01):  # Less than 10 mV difference
            warnings_idx = np.where(np.abs(dV) < 0.01)[0]
            print(f"Warning: Small voltage differences for filters: {warnings_idx + 1}")
            print("Linear calibration may be inaccurate for these filters.")
    
    def voltage_to_power(self, voltages, filter_nums=None, clip_to_noise_floor=True):
        """
        Convert filter detector voltages to power using linear calibration.
        
        Parameters
        ----------
        voltages : float or ndarray
            Filter detector voltage(s) in volts.
            - If 1D array with length n_filters: voltages for all filters at one frequency
            - If 2D array (n_freq, n_filters): voltages for all filters at multiple frequencies
            - If scalar and filter_nums specified: voltage for specific filter(s)
        filter_nums : int or array-like, optional
            Filter number(s) (1-indexed, e.g., 1-21). Required if voltages is scalar or 
            if you want to convert specific filter(s). If None, assumes voltages has 
            shape that matches all filters.
        clip_to_noise_floor : bool, optional
            If True, clip extrapolated powers below the detector noise floor to avoid
            reporting physically impossible values (default: True). The AD8318 cannot
            measure below ~-60 to -65 dBm; linear extrapolation from out-of-band
            voltages can give nonsense values like -120 dBm.
        
        Returns
        -------
        powers : float or ndarray
            Power in dBm, same shape as voltages input
        
        Examples
        --------
        >>> # Convert all 21 filters at one frequency point
        >>> voltages_at_930MHz = np.array([0.5, 0.52, ...])  # 21 values
        >>> powers = calib.voltage_to_power(voltages_at_930MHz)
        
        >>> # Convert all 21 filters at multiple frequencies
        >>> voltages_all = np.random.rand(300, 21)  # 300 freq points × 21 filters
        >>> powers_all = calib.voltage_to_power(voltages_all)
        
        >>> # Convert specific filter(s)
        >>> power_filt5 = calib.voltage_to_power(0.5, filter_nums=5)
        >>> powers_subset = calib.voltage_to_power([0.5, 0.6], filter_nums=[5, 10])
        """
        voltages = np.atleast_1d(voltages)
        
        if filter_nums is not None:
            # Specific filter(s) specified (convert to 0-indexed)
            filter_nums = np.atleast_1d(filter_nums) - 1
            slopes = self.slopes[filter_nums]
            intercepts = self.intercepts[filter_nums]
            powers = slopes * voltages + intercepts
        else:
            # Assume voltages array matches filter structure
            if voltages.ndim == 1:
                # 1D array: all filters at one frequency
                powers = self.slopes * voltages + self.intercepts
            elif voltages.ndim == 2:
                # 2D array (n_freq, n_filters): broadcast calibration
                powers = self.slopes[np.newaxis, :] * voltages + self.intercepts[np.newaxis, :]
            else:
                raise ValueError(f"Voltages array has unexpected shape: {voltages.shape}")
        
        # Clip to detector noise floor to avoid nonsense extrapolation
        if clip_to_noise_floor:
            powers = np.maximum(powers, self.detector_noise_floor_dbm)
        
        # Return scalar if input was scalar
        if powers.size == 1:
            return float(powers.item())
        return powers
    
    def info(self):
        """Print calibration information."""
        print(f"Filter Detector Linear Calibration")
        print(f"  Cycle: {self.cycle_dir.name}")
        print(f"  Number of filters: {self.n_filters}")
        print(f"  Calibration method: Two-point at each filter's center frequency")
        if self.apply_s21:
            print(f"  Calibration reference: Detector input power (with S21 corrections)")
        else:
            print(f"  Calibration reference: LO output power (no S21 corrections)")
        print(f"  Power range: {np.min(self.powers_low):.2f} to {np.max(self.powers_high):.2f} dBm")
        print(f"  Voltage range: {np.min(self.voltages_high):.3f} to {np.max(self.voltages_low):.3f} V")
        print(f"  Slope range: {np.min(self.slopes):.2f} to {np.max(self.slopes):.2f} dBm/V")
        print(f"  Slope mean: {np.mean(self.slopes):.2f} dBm/V, std: {np.std(self.slopes):.2f} dBm/V")
        print(f"  Detector noise floor: {self.detector_noise_floor_dbm:.1f} dBm (clips extrapolation)")


# Convenience functions
def load_lo_power(fits_file, calibration_file=None):
    """
    Load LO power vs frequency from calibration FITS file.
    
    Parameters
    ----------
    fits_file : str or Path
        Path to filtercal_+5dBm.fits or filtercal_-4dBm.fits
    calibration_file : str or Path, optional
        Path to log detector calibration CSV. If None, uses default.
    
    Returns
    -------
    LOPowerLoader
        Object containing frequencies, voltages, and powers
        Use .get_power_at_frequency(freq) to get power at specific frequency
    """
    if calibration_file is not None:
        calib = LogDetectorCalibration(calibration_file)
    else:
        calib = LogDetectorCalibration()
    
    return LOPowerLoader(fits_file, calib)


def get_lo_power_correction(cycle_dir, power_setting='+5dBm', reference='mean'):
    """
    Get LO power correction function for a specific cycle.
    
    This is the recommended way to get power corrections for filter calibration.
    
    Parameters
    ----------
    cycle_dir : str or Path
        Path to cycle directory containing filtercal_*.fits files
    power_setting : str, optional
        Which power setting to use: '+5dBm' or '-4dBm' (default: '+5dBm')
    reference : float or 'mean' or 'median', optional
        Reference power level for corrections (default: 'mean')
    
    Returns
    -------
    callable
        Function that takes frequency (MHz) and returns correction (dB)
    
    Example
    -------
    >>> get_correction = get_lo_power_correction('/path/to/cycle', power_setting='-4dBm')
    >>> correction_at_930MHz = get_correction(930.0)
    >>> # Apply to measurement:
    >>> normalized_power = measured_power_dBm - correction_at_930MHz
    """
    cycle_dir = Path(cycle_dir)
    fits_file = cycle_dir / f"filtercal_{power_setting}.fits"
    
    if not fits_file.exists():
        raise FileNotFoundError(f"Calibration file not found: {fits_file}")
    
    loader = load_lo_power(fits_file)
    
    # Return a function that computes correction at any frequency
    def correction_func(freq):
        return loader.get_power_correction(freq, reference=reference)
    
    return correction_func
