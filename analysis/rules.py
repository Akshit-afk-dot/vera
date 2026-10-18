"""Batch anomaly rules over per-channel scalar features (v0).

Every rule compares a channel with its own batch via robust z-scores (median/MAD) plus absolute sanity
limits. Thresholds are v0 defaults to be tuned on R2 planted-fault results, not domain-validated yet.
Returns plain dicts shaped like contracts.models.Flag so the sandbox needs no pydantic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from analysis.stats import robust_z

Z_FLAG = 3.5
DEAD_CAPACITY_FRACTION = 0.10  # absolute limit: below 10% of batch median capacity = dead channel

# feature -> (fault type, direction, unit); direction -1 flags low values, +1 high, 0 both
RULES: dict[str, tuple[str, int, str]] = {
    "capacity_ah": ("LOW_CAPACITY", -1, "Ah"),
    "ir_mohm": ("HIGH_IR", +1, "mOhm"),
    "first_cycle_ce": ("LOW_CE", -1, ""),
    "dqdv_peak_v": ("CURVE_SHAPE", 0, "V"),
    "capacity_slope_pct_per_cycle": ("CAPACITY_CREEP_UP", +1, "%/cycle"),
    "noise_mv": ("NOISY_OR_DEAD_CHANNEL", +1, "mV"),
}


def severity(z: float) -> str:
    a = abs(z)
    return "low" if a < 5 else "medium" if a < 8 else "high"


def detect(channel_ids: Sequence[str], features: Mapping[str, Sequence[float | None]]) -> dict[str, list[dict]]:
    """features: name -> one value per channel (None/NaN = not measured). Returns channel_id -> flags."""
    flags: dict[str, list[dict]] = {ch: [] for ch in channel_ids}
    cap = np.array([np.nan if x is None else x for x in features.get("capacity_ah", [])], dtype=float)
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

    for name, (fault, direction, unit) in RULES.items():
        if name not in features:
            continue
        vals = np.array([np.nan if x is None else x for x in features[name]], dtype=float)
        live = np.array([ch not in dead for ch in channel_ids])
        if live.sum() < 5:
            continue
        z_live, med, _ = robust_z(vals[live])
        z = np.full(vals.shape, np.nan)
        z[live] = z_live
        for ch, value, zi in zip(channel_ids, vals, z, strict=True):
            if not np.isfinite(zi):
                continue
            hit = zi < -Z_FLAG if direction < 0 else zi > Z_FLAG if direction > 0 else abs(zi) > Z_FLAG
            if not hit:
                continue
            rule = f"robust_z {'<' if direction < 0 else '>'} {'-' if direction < 0 else ''}{Z_FLAG}"
            if direction == 0:
                rule = f"|robust_z| > {Z_FLAG}"
            flags[ch].append({"type": fault, "severity": severity(zi), "evidence": [{
                "metric": name, "value": round(float(value), 5), "unit": unit,
                "batch_median": round(float(med), 5), "robust_z": round(float(zi), 2), "threshold": rule}]})
    return flags
