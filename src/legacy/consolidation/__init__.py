"""
Filterbank Data Consolidation Module

Converts individual spectrum FITS files into consolidated cycle-based
directories with image cube format for efficient storage and analysis.
"""

from . import consolidate
from . import validate
from . import calibration

__all__ = ['consolidate', 'validate', 'calibration']
