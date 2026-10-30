"""Small equivalent-circuit cell simulator for SYNTHETIC formation + grading batches.

V = OCV(soc) + I * (R0 + R1 * (1 - exp(-t / tau1)))   during a current step (I > 0 = charge)
V = OCV(soc) + I_prev * R1 * exp(-t / tau1)           during rest
CC-CV charge: CC until V reaches V_MAX, then exponential current taper until I < CV_CUTOFF_C * C.
Each phase is evaluated vectorised on its own time grid, so a 128-channel batch takes seconds.
This is a plausibility model for testing Vera, not a physics-grade electrochemical model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.interpolate import PchipInterpolator

V_MAX, V_MIN = 4.20, 2.80
CV_CUTOFF_C = 0.05
LOG_DT_S = 60.0          # tester log interval
STEP_START_DT_S = 1.0    # testers log one sample right after each step change (used for the IR proxy)
REST_S = 600.0
TAU1_S = 60.0

# NMC/graphite-like open-circuit voltage, monotone in SOC
_SOC = np.array([0.0, 0.02, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 1.0])
_OCV = np.array([2.80, 3.25, 3.45, 3.55, 3.62, 3.66, 3.70, 3.75, 3.82, 3.90, 3.98, 4.07, 4.12, 4.20])
_OCV_CURVE = PchipInterpolator(_SOC, _OCV)  # smooth and monotone, so dQ/dV has well-defined peaks


@dataclass
class Cell:
    capacity_ah: float
    r0_ohm: float
    r1_ohm: float
    first_cycle_ce: float = 0.88
    creep_pct_per_cycle: float = 0.10
    ocv_bump_v: float = 0.0          # CURVE_SHAPE fault: plateau distortion around mid SOC
    noise_v: float = 0.0005
    dead: bool = False
    temp_c: float = 25.0
    rng: np.random.Generator = field(default_factory=np.random.default_rng, repr=False)

    def ocv(self, soc: np.ndarray) -> np.ndarray:
        s = np.clip(soc, 0.0, 1.0)
        return _OCV_CURVE(s) + self.ocv_bump_v * np.exp(-((s - 0.45) / 0.12) ** 2)


def _grid(duration_s: float) -> np.ndarray:
    """Log times within a step: one sample right after the step change, then every LOG_DT_S."""
    t = np.arange(LOG_DT_S, duration_s, LOG_DT_S)
    return np.concatenate([[STEP_START_DT_S], t, [duration_s]]) if duration_s > STEP_START_DT_S else np.array([duration_s])


def simulate_cycle(cell: Cell, cycle: int, c_rate: float, soc0: float, cap_ah: float) -> tuple[list[dict], float]:
    """One CC-CV charge, rest, CC discharge, rest. Returns phase records and the final SOC."""
    i_cc = c_rate * cell.capacity_ah
    eff = cell.first_cycle_ce if cycle == 1 else 0.997       # charge efficiency (SEI loss on cycle 1)
    phases = []

    # CC charge: soc rises linearly; stop when terminal voltage reaches V_MAX (2 s cut-off resolution)
    t = np.arange(0, 1.6 * 3600 / c_rate, 2.0)
    soc = soc0 + eff * i_cc * t / 3600 / cap_ah
    v = cell.ocv(soc) + i_cc * (cell.r0_ohm + cell.r1_ohm * (1 - np.exp(-t / TAU1_S)))
    k = int(np.argmax(v >= V_MAX)) if np.any(v >= V_MAX) else len(t) - 1
    t_cc, soc_cc = float(t[k]), float(soc[k])
    tg = _grid(t_cc)
    phases.append({"step": "cc_charge", "t": tg, "i": np.full_like(tg, i_cc),
                   "v": cell.ocv(soc0 + eff * i_cc * tg / 3600 / cap_ah)
                   + i_cc * (cell.r0_ohm + cell.r1_ohm * (1 - np.exp(-tg / TAU1_S)))})

    # CV taper: deliver the remaining charge with I = i_cc * exp(-t/tau) until I < cutoff
    i_cut = CV_CUTOFF_C * cell.capacity_ah
    remaining_ah = max((1.0 - soc_cc) * cap_ah / eff, 1e-4)
    tau = remaining_ah * 3600 / max(i_cc - i_cut, 1e-6)
    t_cv = tau * np.log(i_cc / i_cut)
    tg = _grid(t_cv)
    phases.append({"step": "cv_charge", "t": tg, "i": i_cc * np.exp(-tg / tau), "v": np.full_like(tg, V_MAX)})
    soc_full = min(1.0, soc_cc + eff * i_cc * tau * (1 - i_cut / i_cc) / 3600 / cap_ah)

    # Rest after charge: polarisation relaxes
    tg = _grid(REST_S)
    phases.append({"step": "rest", "t": tg, "i": np.zeros_like(tg),
                   "v": cell.ocv(np.full_like(tg, soc_full)) + i_cut * cell.r1_ohm * np.exp(-tg / TAU1_S)})

    # CC discharge until V_MIN
    t = np.arange(0, 1.6 * 3600 / c_rate, 2.0)
    soc = soc_full - i_cc * t / 3600 / cap_ah
    v = cell.ocv(soc) - i_cc * (cell.r0_ohm + cell.r1_ohm * (1 - np.exp(-t / TAU1_S)))
    k = int(np.argmax((v <= V_MIN) | (soc <= 0))) if np.any((v <= V_MIN) | (soc <= 0)) else len(t) - 1
    t_dc = float(t[k])
    tg = _grid(t_dc)
    soc_t = soc_full - i_cc * tg / 3600 / cap_ah
    phases.append({"step": "cc_discharge", "t": tg, "i": np.full_like(tg, -i_cc),
                   "v": cell.ocv(soc_t) - i_cc * (cell.r0_ohm + cell.r1_ohm * (1 - np.exp(-tg / TAU1_S)))})
    soc_end = float(soc_t[-1])

    tg = _grid(REST_S)
    phases.append({"step": "rest", "t": tg, "i": np.zeros_like(tg),
                   "v": cell.ocv(np.full_like(tg, soc_end)) - i_cc * cell.r1_ohm * np.exp(-tg / TAU1_S)})
    return phases, soc_end


def simulate_cell(cell: Cell, protocol: list[float]) -> dict[str, np.ndarray]:
    """protocol: C-rate per cycle (e.g. [0.2, 0.2, 0.2, 0.5] = 3 formation + 1 grading).
    Returns canonical columns for one channel."""
    cols: dict[str, list] = {k: [] for k in ("cycle", "step", "time_s", "voltage_v", "current_a", "temperature_c")}
    t0, soc, step_no = 0.0, 0.0, 0
    n = len(protocol)
    for c, rate in enumerate(protocol, start=1):
        cap = cell.capacity_ah * (1 + cell.creep_pct_per_cycle / 100 * (c - n))  # grading cycle = nominal
        phases, soc = simulate_cycle(cell, c, rate, soc, cap)
        for ph in phases:
            step_no += 1
            m = len(ph["t"])
            cols["cycle"].append(np.full(m, c))
            cols["step"].append(np.full(m, step_no))
            cols["time_s"].append(t0 + ph["t"])
            cols["voltage_v"].append(ph["v"])
            cols["current_a"].append(ph["i"])
            cols["temperature_c"].append(cell.temp_c + 0.4 * np.abs(ph["i"]) / cell.capacity_ah)
            t0 += float(ph["t"][-1])
    out = {k: np.concatenate(v) for k, v in cols.items()}
    m = len(out["time_s"])
    if cell.dead:  # no contact: tester reads ~0 V and cannot drive current
        out["voltage_v"] = 0.002 + cell.rng.normal(0, 0.001, m)
        out["current_a"] = np.zeros(m)
    else:
        out["voltage_v"] = out["voltage_v"] + cell.rng.normal(0, cell.noise_v, m)
    out["temperature_c"] = out["temperature_c"] + cell.rng.normal(0, 0.05, m)
    return out
