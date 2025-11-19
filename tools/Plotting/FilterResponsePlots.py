import os, glob, copy
import re
import numpy as np
import matplotlib.pyplot as plt
from astropy.io import fits

pjoin = os.path.join

data_path = '/media/peterson/INDURANCE'
analysis_path = '/home/peterson/highz/highz-filterbank/tools/Plotting'
#bandpass_path = pjoin(data_path, 'Continuous_Sweep')
calib_path = pjoin(data_path, 'FilterCalibrations')

#spec_data_1 = pjoin(bandpass_path, '10012025_141849.fits')
#cal_data_1 = pjoin(calib_path, '10012025_145234.fits')

# Known fixed centers (21 filters, 904 → 956 in 2.6 MHz steps)
centers_mhz_fixed = 904.0 + 2.6 * np.arange(21)

def inspect_fits_table(path, hdu_index=1, preview_rows=5):
    print("Inspecting:", path)
    with fits.open(path, memmap=True) as hdul:
        hdul.info()
        hdu = hdul[hdu_index]
        hdr = hdu.header
        print("\n--- Selected header keys ---")
        for k in ["NAXIS","NAXIS1","NAXIS2","BUNIT",
                  "CTYPE1","CUNIT1","CRVAL1","CDELT1","CRPIX1","CD1_1",
                  "LO_FREQ","LO_MHZ","IF_FREQ","IF_MHZ","STEP"]:
            if k in hdr:
                print(f"{k:>10}: {hdr[k]}")
        xt = hdr.get("XTENSION","").upper()
        if xt in {"BINTABLE","TABLE"}:
            print("\n--- Columns ---")
            print(hdu.columns)  # includes names, formats, units
            print("\n--- First rows (shapes only for array-fields) ---")
            data = hdu.data
            n = min(preview_rows, len(data))
            for i in range(n):
                row = data[i]
                print(f"row {i}:")
                for name in hdu.columns.names:
                    val = row[name]
                    if hasattr(val, "__len__") and not isinstance(val, (bytes, str, np.bytes_)):
                        arr = np.asarray(val)
                        print(f"  {name}: shape={arr.shape}, dtype={arr.dtype}")
                    else:
                        print(f"  {name}: {val}")
        else:
            print("HDU is not a table; switch hdu_index.")

def _to_str(v):
    import numpy as np
    if isinstance(v, (bytes, np.bytes_)):
        return v.decode(errors="ignore")
    return str(v)

def _parse_freq_mhz(s):
    if s is None: return np.nan
    s = _to_str(s).strip()
    m = re.search(r"([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", s)
    if not m: return np.nan
    val = float(m.group(1)); low = s.lower()
    if   "ghz" in low: return val * 1e3
    elif "mhz" in low: return val
    elif "khz" in low: return val / 1e3
    elif "hz"  in low: return val / 1e6
    return val  # assume MHz

def load_filterbank_table(path, hdu_index=1,
                          cols=("ADHAT_1","ADHAT_2","ADHAT_3"),
                          freq_col="FREQUENCY"):
    with fits.open(path, memmap=True) as hdul:
        hdu = hdul[hdu_index]
        assert hdu.header.get("XTENSION","").upper() in {"BINTABLE","TABLE"}
        tbl = hdu.data
        blocks = []
        for c in cols:
            cname = next((nm for nm in hdu.columns.names if nm.upper()==c.upper()), None)
            if cname is None:
                raise KeyError(f"Column '{c}' not found. Available: {hdu.columns.names}")
            arr = np.asarray([np.ravel(x) for x in np.asarray(tbl[cname])])  # (n_steps, width)
            blocks.append(arr)
        data21 = np.concatenate(blocks, axis=1).astype(float)  # (n_steps, 21)

        cfreq = next((nm for nm in hdu.columns.names if nm.upper()==freq_col.upper()), None)
        lo_mhz = (np.array([_parse_freq_mhz(v) for v in tbl[cfreq]], dtype=float)
                  if cfreq is not None else np.arange(len(tbl), dtype=float))
        return lo_mhz, data21

# --- Conversions ---
def adc_counts_to_voltage(counts,
                          ref=3.27,
                          mode="c_like",
                          denom_pos=2147483647.8,   # from your commented C
                          denom_neg=2147483648.0):  # from your commented C
    """
    Convert ADS1263 ADC 'counts' to Volts.

    Parameters
    ----------
    counts : array-like
        Raw ADC codes (often stored as floats in files).
    ref : float
        Reference voltage (Volts). Your code uses 3.27 V.
    mode : {"c_like","signed_bipolar"}
        - "c_like": replicate the exact C snippet you shared, mapping to ~0..ref V.
        - "signed_bipolar": interpret as true signed int32 (±ref full-scale).
    denom_pos, denom_neg : float
        Denominators used in the C-like mapping (kept tunable).

    Returns
    -------
    V : ndarray (float)
        Volt values (same shape as counts).
    """
    c = np.asarray(counts)

    if mode == "c_like":
        # Work with float arrays; derive sign from MSB as if counts were uint32
        # (If 'counts' came in negative, we still only look at the MSB bit.)
        # Convert to unsigned 64 so bit math is well-defined.
        cu = c.astype(np.uint64)
        neg = ((cu >> 31) & 0x1) == 1  # MSB set

        V = np.empty_like(c, dtype=float)
        # Negative branch (MSB=1)
        V[neg]  = ref*2.0 - (cu[neg].astype(float)/denom_neg)*ref
        # Positive branch (MSB=0)
        V[~neg] = (cu[~neg].astype(float)/denom_pos)*ref
        return V

    elif mode == "signed_bipolar":
        # Interpret as true signed int32 counts (two's complement)
        cs = c.astype(np.int64)  # safe up-cast
        # Convert any values that were stored as 0..2^32-1 back to signed:
        # (If your data are already negative for neg codes, this is a no-op.)
        cs = ((cs + (1<<31)) % (1<<32)) - (1<<31)
        # Map ±(2^31-1) -> ±ref
        V = (cs / float((1<<31) - 1)) * ref
        return V

    else:
        raise ValueError("mode must be 'c_like' or 'signed_bipolar'.")


def voltage_to_dbm(V,
                   R=50.0,
                   assume="rms"):
    """
    Convert Volts to power in dBm for a resistive load R.

    Parameters
    ----------
    V : array-like
        Volt values.
    R : float
        Load resistance in ohms (50 Ω typical).
    assume : {"rms","peak"}
        If your voltages are peak, set assume="peak" to convert to Vrms.

    Returns
    -------
    dBm : ndarray (float)
        Power in dBm. Non-positive powers map to -inf.
    """
    V = np.asarray(V, dtype=float)
    Vrms = V if assume.lower()=="rms" else (V/np.sqrt(2.0))
    P_w = (Vrms**2) / R
    with np.errstate(divide="ignore", invalid="ignore"):
        dbm = 10.0 * np.log10(P_w / 1e-3)
    dbm[~np.isfinite(dbm)] = -np.inf
    return dbm

def plot_filters_overlay_voltage(lo_mhz, data21, filters="all", title=None, logy=False,
                                 ref=3.27, mode="c_like"):
    x = np.asarray(lo_mhz)
    Yc = np.asarray(data21, dtype=float)
    Yv = adc_counts_to_voltage(Yc, ref=ref, mode=mode)

    idxs = list(range(Yv.shape[1])) if filters == "all" else list(filters)
    plt.figure(figsize=(11,6))
    for j in idxs:
        plt.plot(x, Yv[:, j], label=f"Filter {j+1:02d}")
    plt.xlabel("LO Frequency [MHz]")
    plt.ylabel("Voltage [V{}]".format("" if mode=="signed_bipolar" else ""))  # keep label simple
    if logy: plt.yscale("log")
    if title: plt.title(title)
    # if len(idxs) > 1:
    #     plt.legend(ncol=3, fontsize=9)
    plt.ylim(0.7, 2.1)
    plt.grid(True, alpha=0.3)
    plt.savefig(pjoin(analysis_path, 'FilterBank_Response_+5dBm_In-situ_Nov2nd.png'))
    plt.show()


def plot_filters_overlay_dbm(lo_mhz, data21, filters="all", title=None, logy=False,
                             ref=3.27, mode="c_like", R=50.0, assume="rms"):
    x = np.asarray(lo_mhz)
    Yc = np.asarray(data21, dtype=float)
    Yv = adc_counts_to_voltage(Yc, ref=ref, mode=mode)
    Yd = voltage_to_dbm(Yv, R=R, assume=assume)

    idxs = list(range(Yd.shape[1])) if filters == "all" else list(filters)
    plt.figure(figsize=(11,6))
    for j in idxs:
        plt.plot(x, Yd[:, j], label=f"Filter {j+1:02d}")
    plt.xlabel("LO Frequency [MHz]")
    plt.ylabel("Power [dBm] (R={}Ω, {}-assumed)".format(R, assume.upper()))
    if logy: plt.yscale("log")
    if title: plt.title(title)
    if len(idxs) > 1:
        plt.legend(ncol=3, fontsize=9)
    plt.grid(True, alpha=0.3)
    plt.show()


def plot_filters_heatmap_voltage(lo_mhz, data21, title=None, ref=3.27, mode="c_like"):
    x = np.asarray(lo_mhz, dtype=float)
    Yv = adc_counts_to_voltage(np.asarray(data21, dtype=float), ref=ref, mode=mode).T
    plt.figure(figsize=(11,5))
    extent = [np.nanmin(x), np.nanmax(x), -0.5, Yv.shape[0]-0.5]
    im = plt.imshow(Yv, aspect="auto", origin="lower", extent=extent)
    plt.colorbar(im, label="Voltage [V]")
    plt.yticks(range(Yv.shape[0]), [f"{i+1:02d}" for i in range(Yv.shape[0])])
    plt.xlabel("LO Frequency [MHz]")
    plt.ylabel("Filter index")
    if title: plt.title(title)
    plt.savefig(pjoin(analysis_path, 'FilterBank_Response_Heatmap_+5dBm_In-situ_Nov2nd.png'))
    plt.show()


def plot_filters_heatmap_dbm(lo_mhz, data21, title=None, ref=3.27, mode="c_like",
                             R=50.0, assume="rms"):
    x = np.asarray(lo_mhz, dtype=float)
    Yv = adc_counts_to_voltage(np.asarray(data21, dtype=float), ref=ref, mode=mode)
    Yd = voltage_to_dbm(Yv, R=R, assume=assume).T
    plt.figure(figsize=(11,5))
    extent = [np.nanmin(x), np.nanmax(x), -0.5, Yd.shape[0]-0.5]
    im = plt.imshow(Yd, aspect="auto", origin="lower", extent=extent)
    plt.colorbar(im, label="Power [dBm]")
    plt.yticks(range(Yd.shape[0]), [f"{i+1:02d}" for i in range(Yd.shape[0])])
    plt.xlabel("LO Frequency [MHz]")
    plt.ylabel("Filter index")
    if title: plt.title(title)
    plt.show()

filename1 = '11022025_125350_+5dBm.fits'
filename2 = '11022025_125357_-4dBm.fits'
LO = "_LO_1_"
cal_file_1   = pjoin(calib_path, filename1)
lo_cal_1,  Ycal_1  = load_filterbank_table(cal_file_1)
lo_cal_1.shape, Ycal_1.shape

# # Voltage quicklooks
plot_filters_overlay_voltage(lo_cal_1, Ycal_1, title="Bandpass Calibration sweep (Voltage)", ref=5, mode="c_like")
plot_filters_heatmap_voltage(lo_cal_1, Ycal_1, title=filename1+LO+"Bandpass Calibration sweep heatmap (Voltage)", ref=5, mode="c_like")

# cal_file_2   = pjoin(calib_path, filename2)
# lo_cal_2,  Ycal_2  = load_filterbank_table(cal_file_2)
# lo_cal_2.shape, Ycal_2.shape

# # Voltage quicklooks
# plot_filters_overlay_voltage(lo_cal_2, Ycal_2, title="Bandpass Calibration sweep (Voltage)", ref=5, mode="c_like")
# plot_filters_heatmap_voltage(lo_cal_2, Ycal_2, title=filename2+LO+"Bandpass Calibration sweep heatmap (Voltage)", ref=5, mode="c_like")









# dBm quicklooks (50 Ω system, interpreting Volt values as RMS)
# plot_filters_overlay_dbm(lo_cal, Ycal, filters=[9,10], title="Bandpass Calibration sweep (dBm)", ref=5, mode="c_like", R=50.0, assume="rms")
# plot_filters_heatmap_dbm(lo_cal, Ycal, title="Bandpass Calibration sweep heatmap (dBm)", ref=3.27, mode="c_like", R=50.0, assume="rms")
