"""Generic helpers available to model-written normalizers. No per-format logic lives here."""

import numpy as np
import pandas as pd


def hhmmss_to_seconds(values) -> pd.Series:
    """'hh:mm:ss', 'hh:mm:ss.f' or 'd.hh:mm:ss' strings to seconds."""
    s = pd.Series(values).astype(str).str.strip()
    days = s.str.extract(r"^(\d+)\.(?=\d+:)")[0].fillna(0).astype(float)
    t = s.str.replace(r"^\d+\.(?=\d+:)", "", regex=True).str.split(":", expand=True).astype(float)
    sec = t[0] * 3600 + t[1] * 60 + (t[2] if t.shape[1] > 2 else 0)
    return days * 86400 + sec


def matlab_datenum_to_seconds(values) -> np.ndarray:
    """MATLAB datenum (days) to seconds since the first sample."""
    x = np.asarray(values, dtype=float)
    return (x - x.flat[0]) * 86400.0


def steps_from_current(current, threshold=None) -> np.ndarray:
    """Number consecutive segments of the same current sign (charge / rest / discharge), starting at 1."""
    i = np.asarray(current, dtype=float)
    thr = threshold if threshold is not None else max(1e-3, 0.01 * np.nanmax(np.abs(i)) if i.size else 1e-3)
    mode = np.where(i > thr, 1, np.where(i < -thr, -1, 0))
    return np.cumsum(np.r_[True, mode[1:] != mode[:-1]]).astype(int)


def cycles_from_current(current, threshold=None) -> np.ndarray:
    """Cycle index starting at 1; a new cycle starts at each charge that follows a discharge.
    Expects positive = charge."""
    i = np.asarray(current, dtype=float)
    thr = threshold if threshold is not None else max(1e-3, 0.01 * np.nanmax(np.abs(i)) if i.size else 1e-3)
    mode = np.where(i > thr, 1, np.where(i < -thr, -1, 0))
    cycle, seen_discharge, out = 1, False, np.empty(i.size, dtype=int)
    for k, m in enumerate(mode):
        if m == -1:
            seen_discharge = True
        elif m == 1 and seen_discharge:
            cycle += 1
            seen_discharge = False
        out[k] = cycle
    return out
