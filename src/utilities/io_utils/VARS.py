# Configuration defaults
DEFAULT_DATA_DIR = "/media/peterson/INDURANCE/Data"
DEFAULT_REFRESH_INTERVAL = 3000  # milliseconds (3 seconds)

# Calibration alignment defaults
DEFAULT_ALIGN_FREQ_MIN = 50  # MHz
DEFAULT_ALIGN_FREQ_MAX = 80  # MHz

ADC_REFERENCE_VOLTAGE = 2.5  # V (log detector ADC reference)


"""Path resolution helpers for runtime data assets."""

from pathlib import Path
import os

def get_default_s21_dir():
    """Return the default S21 directory with environment override support.

    Resolution order:
    1. ``HIGHZ_FILTERBANK_S21_DIR`` environment variable if set.
    2. Repository-relative path: ``<repo>/characterization/s_parameters``.

    This keeps editable installs and source checkouts portable while allowing
    users of built packages to configure an external calibration path.
    """
    env_override = os.environ.get("HIGHZ_FILTERBANK_S21_DIR")
    if env_override:
        return env_override

    repo_s21_dir = Path(__file__).resolve().parents[3] / "characterization" / "s_parameters"
    return str(repo_s21_dir)


def get_default_calibration_file():
    """Return the default log-detector calibration file with env override.

    Resolution order:
    1. ``HIGHZ_FILTERBANK_CALIBRATION_FILE`` environment variable if set.
    2. Repository-relative path:
       ``<repo>/characterization/log_detector/calibration_20260226.csv``.
    """
    env_override = os.environ.get("HIGHZ_FILTERBANK_CALIBRATION_FILE")
    if env_override:
        return env_override

    repo_calibration_file = (
        Path(__file__).resolve().parents[3]
        / "characterization"
        / "log_detector"
        / "calibration_20260226.csv"
    )
    return str(repo_calibration_file)

DEFAULT_S21_DIR = get_default_s21_dir()
DEFAULT_CALIBRATION_FILE = get_default_calibration_file()