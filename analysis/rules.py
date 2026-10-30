"""Batch anomaly rules over per-channel scalar features.

Every rule compares a channel with its own batch via robust z-scores (median/MAD) plus absolute sanity
limits. Positive, right-skewed metrics (noise, curve distance) are scored on a log scale so that their
natural skew does not read as anomalies. The threshold is pre-registered at |z| > 3.5 and reported, with a
sweep, in results/r2_detection.md. Returns plain dicts shaped like contracts.models.Flag (no pydantic).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from analysis.stats import robust_z

Z_FLAG = 3.5
DEAD_CAPACITY_FRACTION = 0.10  # absolute limit: below 10% of batch median capacity = dead channel
# On a channel already flagged noisy, metrics measured from a few samples are not trustworthy; flags from them
# are dropped (the channel is rejected for noise anyway). Without this, noise reads as resistance or shape faults.
NOISE_SENSITIVE = {"HIGH_IR", "CURVE_SHAPE"}

# feature -> (fault type, direction, unit, scale); direction -1 flags low values, +1 high
RULES: dict[str, tuple[str, int, str, str]] = {
    "capacity_ah": ("LOW_CAPACITY", -1, "Ah", "linear"),
    "ir_mohm": ("HIGH_IR", +1, "mOhm", "linear"),
    "first_cycle_ce": ("LOW_CE", -1, "", "linear"),
    "curve_dist_pct": ("CURVE_SHAPE", +1, "%", "log"),  # offset-aligned Q(V) gap to the batch median curve
    "capacity_slope_pct_per_cycle": ("CAPACITY_CREEP_UP", +1, "%/cycle", "linear"),
    "noise_mv": ("NOISY_OR_DEAD_CHANNEL", +1, "mV", "log"),
}


def severity(z: float) -> str:
    a = abs(z)
    return "low" if a < 5 else "medium" if a < 8 else "high"


def _as_array(values: Sequence[float | None]) -> np.ndarray:
    return np.array([np.nan if x is None else x for x in values], dtype=float)


def detect(channel_ids: Sequence[str], features: Mapping[str, Sequence[float | None]],
           z_flag: float = Z_FLAG) -> dict[str, list[dict]]:
    """features: name -> one value per channel (None/NaN = not measured). Returns channel_id -> flags."""
    flags: dict[str, list[dict]] = {ch: [] for ch in channel_ids}
    cap = _as_array(features.get("capacity_ah", []))
    dead = set()
    if cap.size:
        med_cap = float(np.nanmedian(cap))
        for ch, c in zip(channel_ids, cap, strict=True):
            if not np.isfinite(c) or c < DEAD_CAPACITY_FRACTION * med_cap:
                dead.add(ch)
                flags[ch].append({"type": "NOISY_OR_DEAD_CHANNEL", "severity": "high", "evidence": [{
                    "metric": "capacity_ah", "value": 0.0 if not np.isfinite(c) else round(float(c), 4), "unit": "Ah",
                    "batch_median": round(med_cap, 4), "robust_z": None,
                    "threshold": f"capacity < {DEAD_CAPACITY_FRACTION:.0%} of batch median"}]})

    live = np.array([ch not in dead for ch in channel_ids])
    for name, (fault, direction, unit, scale) in RULES.items():
        if name not in features:
            continue
        vals = _as_array(features[name])
        scored = np.log(np.where(vals > 0, vals, np.nan)) if scale == "log" else vals
        if np.isfinite(scored[live]).sum() < 5:
            continue
        z = np.full(vals.shape, np.nan)
        z[live] = robust_z(scored[live])[0]
        med = float(np.nanmedian(vals[live]))
        rule = f"robust_z{' (log scale)' if scale == 'log' else ''} {'<' if direction < 0 else '>'} {-z_flag if direction < 0 else z_flag}"
        for ch, value, zi in zip(channel_ids, vals, z, strict=True):
            if np.isfinite(zi) and (zi < -z_flag if direction < 0 else zi > z_flag):
                flags[ch].append({"type": fault, "severity": severity(zi), "evidence": [{
                    "metric": name, "value": round(float(value), 5), "unit": unit,
                    "batch_median": round(med, 5), "robust_z": round(float(zi), 2), "threshold": rule}]})
    for ch, fs in flags.items():
        if any(f["type"] == "NOISY_OR_DEAD_CHANNEL" for f in fs):
            flags[ch] = [f for f in fs if f["type"] not in NOISE_SENSITIVE]
    return flags
