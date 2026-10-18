"""Robust batch statistics. Plain numpy so this module also runs inside the sandbox image."""

from __future__ import annotations

import numpy as np

MAD_TO_SIGMA = 1.4826  # makes MAD a consistent estimator of sigma for normal data


def robust_center_scale(values: np.ndarray) -> tuple[float, float]:
    """Median and MAD-based sigma over finite values. Falls back to IQR, then std, then 1e-12."""
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return float("nan"), float("nan")
    med = float(np.median(v))
    scale = MAD_TO_SIGMA * float(np.median(np.abs(v - med)))
    if scale <= 0:
        q75, q25 = np.percentile(v, [75, 25])
        scale = float(q75 - q25) / 1.349
    if scale <= 0:
        scale = float(np.std(v))
    return med, max(scale, 1e-12)


def robust_z(values: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Robust z-score of every value against its own batch. Returns (z, median, sigma)."""
    v = np.asarray(values, dtype=float)
    med, scale = robust_center_scale(v)
    return (v - med) / scale, med, scale
