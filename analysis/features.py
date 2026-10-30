"""Per-channel and per-cycle features from the canonical table. Plain numpy/pandas (runs in the sandbox too).

Canonical columns: channel_id, cycle, step, time_s, voltage_v, current_a (+ optional capacity_ah, temperature_c).
Current sign: positive = charge. Every number Vera reports about a cell comes from this module or rules/grading.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

VGRID = np.arange(3.45, 4.05, 0.002)   # voltage axis for curve-shape comparison (IR-compensated)
CURVE_POINTS = 60                      # downsampled points per cycle sent to the UI


def _modes(i: np.ndarray) -> np.ndarray:
    thr = max(0.002, 0.01 * float(np.nanmax(np.abs(i)))) if i.size else 0.002
    return np.where(i > thr, 1, np.where(i < -thr, -1, 0))


def _increments(t: np.ndarray, i: np.ndarray, mode: np.ndarray) -> np.ndarray:
    """Charge (Ah) moved in the interval ending at each sample: trapezoid inside a step, the new step's
    current across a step change (testers log one sample right after a change)."""
    dt = np.diff(t, prepend=t[0])
    same = np.r_[False, mode[1:] == mode[:-1]]
    i_prev = np.r_[i[0], i[:-1]]
    return np.where(same, 0.5 * (i + i_prev), i) * dt / 3600.0


def _smooth(y: np.ndarray, sigma_pts: float) -> np.ndarray:
    k = np.arange(-int(4 * sigma_pts), int(4 * sigma_pts) + 1)
    w = np.exp(-0.5 * (k / sigma_pts) ** 2)
    return np.convolve(y, w / w.sum(), mode="same")


def _noise_mv(v: np.ndarray, mode: np.ndarray, t: np.ndarray) -> float:
    """Robust noise from second differences in rest segments, skipping the first 3 minutes of relaxation."""
    seg_start = np.r_[True, mode[1:] != mode[:-1]]
    seg_id = np.cumsum(seg_start)
    t_in_seg = t - pd.Series(t).groupby(seg_id).transform("min").to_numpy()
    sel = (mode == 0) & (t_in_seg >= 180)
    d2 = []
    for s in np.unique(seg_id[sel]):
        x = v[sel & (seg_id == s)]
        if x.size >= 3:
            d2.append(np.diff(x, 2))
    if not d2:
        return float("nan")
    d2 = np.concatenate(d2)
    return float(1.4826 * np.median(np.abs(d2)) / np.sqrt(6) * 1000)


def _cycle_features(t, v, i, mode, dq, cyc) -> tuple[list[dict], dict]:
    rows, curves = [], {}
    for c in np.unique(cyc):
        m = cyc == c
        dis, chg = float(-dq[m & (dq < 0)].sum()), float(dq[m & (dq > 0)].sum())
        idx = np.flatnonzero(m)
        ir = None
        starts = idx[(mode[idx] == -1) & (np.r_[0, mode[:-1]][idx] != -1)]
        if starts.size and starts[0] > 0:
            j = starts[0]
            di = abs(i[j]) - abs(i[j - 1])
            if mode[j - 1] == 0 and t[j] - t[j - 1] <= 10 and di > 0:
                ir = float((v[j - 1] - v[j]) / di * 1000)
        dmask = m & (mode == -1)
        mid = float(np.median(v[dmask])) if dmask.any() else None
        rows.append({"cycle": int(c), "discharge_capacity_ah": round(dis, 5), "charge_capacity_ah": round(chg, 5),
                     "ce": round(dis / chg, 5) if chg > 0 else None, "ir_mohm": round(ir, 3) if ir is not None else None,
                     "mid_voltage_v": round(mid, 4) if mid is not None else None})
        if dmask.sum() >= 5:
            q = np.cumsum(-dq[dmask])
            pick = np.linspace(0, q.size - 1, min(CURVE_POINTS, q.size)).astype(int)
            curves[int(c)] = {"q_ah": np.round(q[pick], 4).tolist(), "v": np.round(v[dmask][pick], 4).tolist()}
    return rows, curves


def _qv_shape(v: np.ndarray, q: np.ndarray, current_a: float, ir_ohm: float | None):
    """Normalised discharged charge versus IR-compensated voltage (sorted by voltage), and the dQ/dV peak."""
    if v.size < 10 or q[-1] <= 0:
        return None, None
    v_ocv = v + abs(current_a) * (ir_ohm or 0.0)
    order = np.argsort(v_ocv)
    vx, qy = v_ocv[order], (q / q[-1])[order]
    dqdv = _smooth(-np.gradient(np.interp(VGRID, vx, qy), VGRID), 5)
    core = (VGRID > 3.5) & (VGRID < 4.0)
    peak = float(VGRID[core][np.argmax(dqdv[core])])
    return (vx, qy), peak


def channel_features(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, list[dict]], dict[str, dict]]:
    """Returns (per-channel summary indexed by channel_id, per-cycle records, discharge curves for the UI)."""
    summary, cycles_out, curves_out, shapes = [], {}, {}, {}
    for cid, g in df.sort_values(["channel_id", "time_s"], kind="stable").groupby("channel_id", sort=False):
        t, v, i = g.time_s.to_numpy(float), g.voltage_v.to_numpy(float), g.current_a.to_numpy(float)
        cyc = g.cycle.to_numpy()
        mode = _modes(i)
        dq = _increments(t, i, mode)
        rows, curves = _cycle_features(t, v, i, mode, dq, cyc)
        cycles_out[str(cid)], curves_out[str(cid)] = rows, curves
        last, first = rows[-1], rows[0]
        caps = np.array([r["discharge_capacity_ah"] for r in rows])
        slope = None
        if len(rows) >= 3 and caps[-1] > 0:
            slope = float(np.polyfit(np.arange(len(caps)), caps, 1)[0] / caps[-1] * 100)
        lastmask = (cyc == last["cycle"]) & (mode == -1)
        q = np.cumsum(-dq[lastmask])
        ir = last["ir_mohm"]
        shape, peak = _qv_shape(v[lastmask], q, float(np.median(i[lastmask])) if lastmask.any() else 0.0,
                                ir / 1000 if ir else None)
        shapes[str(cid)] = shape
        summary.append({"channel_id": str(cid), "capacity_ah": last["discharge_capacity_ah"], "ir_mohm": ir,
                        "first_cycle_ce": first["ce"], "capacity_slope_pct_per_cycle": round(slope, 4) if slope is not None else None,
                        "dqdv_peak_v": round(peak, 4) if peak is not None else None,
                        "noise_mv": round(_noise_mv(v, mode, t), 4), "mid_voltage_v": last["mid_voltage_v"],
                        "n_cycles": len(rows)})
    feats = pd.DataFrame(summary).set_index("channel_id")
    feats["curve_dist_pct"] = curve_distance(shapes, feats.index)
    return feats, cycles_out, curves_out


OFFSETS_V = np.arange(-0.060, 0.0605, 0.001)


def curve_distance(shapes: dict, index: pd.Index) -> list[float | None]:
    """Shape-only gap (% of capacity, RMS) between each channel's normalised Q(V) curve and the batch median,
    after the constant voltage offset that best aligns them. A uniform shift (IR, polarisation, rate) costs
    nothing; a local plateau distortion does."""
    valid = {k: s for k, s in shapes.items() if s is not None}
    if len(valid) < 5:
        return [None] * len(index)
    grid = {k: np.interp(VGRID, vx, qy) for k, (vx, qy) in valid.items()}
    med = np.median(np.vstack(list(grid.values())), axis=0)
    out = []
    for k in index:
        if k not in valid:
            out.append(None)
            continue
        vx, qy = valid[k]
        shifted = np.interp(VGRID[None, :] + OFFSETS_V[:, None], vx, qy)
        rms = np.sqrt(np.mean((shifted - med[None, :]) ** 2, axis=1))
        out.append(round(float(rms.min()) * 100, 4))
    return out
