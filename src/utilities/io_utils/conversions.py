"""
Unit conversion utilities for filterbank data

Convert ADC counts to voltage and voltage to power (dBm).
Absorbed from highz_exp.filter_plotting module.
"""

import numpy as np


def adc_counts_to_voltage(counts, ref=3.27, mode="c_like",
                          denom_pos=2147483647.8, denom_neg=2147483648.0):
    """
    Convert ADS1263 ADC counts to Volts.
    
    Parameters
    ----------
    counts : array-like
        Raw ADC codes (often stored as floats in files)
    ref : float
        Reference voltage (Volts). Default 3.27 V, use 5.0 for calibration data
    mode : {"c_like", "signed_bipolar"}
        - "c_like": replicate C-style mapping, resulting in ~0..ref V
        - "signed_bipolar": interpret as true signed int32 (±ref full-scale)
    denom_pos, denom_neg : float
        Denominators used in C-like mapping (kept tunable)
    
    Returns
    -------
    V : ndarray
        Volt values (same shape as counts)
    """
    c = np.asarray(counts)

    if mode == "c_like":
        # Work with float arrays; derive sign from MSB as if counts were uint32
        cu = c.astype(np.uint64)
        neg = ((cu >> 31) & 0x1) == 1  # MSB set

        V = np.empty_like(c, dtype=float)
        # Negative branch (MSB=1)
        V[neg] = ref * 2.0 - (cu[neg].astype(float) / denom_neg) * ref
        # Positive branch (MSB=0)
        V[~neg] = (cu[~neg].astype(float) / denom_pos) * ref
        return V

    elif mode == "signed_bipolar":
        # Interpret as true signed int32 counts (two's complement)
        cs = c.astype(np.int64)  # safe up-cast
        cs = ((cs + (1 << 31)) % (1 << 32)) - (1 << 31)
        # Map ±(2^31-1) -> ±ref
        V = (cs / float((1 << 31) - 1)) * ref
        return V

    else:
        raise ValueError("mode must be 'c_like' or 'signed_bipolar'.")


def voltage_to_dbm(V, R=50.0, assume="rms"):
    """
    Convert Volts to power in dBm for a resistive load.
    
    Parameters
    ----------
    V : array-like
        Volt values
    R : float
        Load resistance in ohms (default: 50 Ω)
    assume : {"rms", "peak"}
        If "peak", convert peak to Vrms first
    
    Returns
    -------
    dBm : ndarray
        Power in dBm (non-positive values map to -inf)
    """
    V = np.asarray(V, dtype=float)
    Vrms = V if assume.lower() == "rms" else (V / np.sqrt(2.0))
    P_w = (Vrms ** 2) / R
    with np.errstate(divide="ignore", invalid="ignore"):
        dbm = 10.0 * np.log10(P_w / 1e-3)
    dbm[~np.isfinite(dbm)] = -np.inf
    return dbm
