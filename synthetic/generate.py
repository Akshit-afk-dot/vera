"""Build a SYNTHETIC formation + grading batch with planted faults and export it in several invented layouts.

uv run python -m synthetic.generate --channels 128 --seed 7 --out data/synthetic/s7
uv run python -m synthetic.generate --channels 128 --seed 101 --clean --out data/synthetic/clean101

Writes canonical.parquet (ground truth), labels.csv (never shown to the agent), meta.json and one file per layout.
Layouts are neutral inventions, not copies of any vendor's format.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from synthetic.cell_model import Cell, simulate_cell

PROTOCOL = [0.2, 0.2, 0.2, 0.5]  # 3 formation cycles at C/5, 1 grading cycle at C/2
NOMINAL_AH = 2.50

# fault -> (field, severity grid); one fault per faulty channel
FAULTS: dict[str, list[float]] = {
    "LOW_CAPACITY": [0.02, 0.04, 0.08, 0.15],          # fraction of capacity lost
    "HIGH_IR": [0.10, 0.25, 0.50, 1.00],               # fractional resistance increase
    "CURVE_SHAPE": [0.010, 0.020, 0.040, 0.060],        # V plateau bump at mid SOC
    "CAPACITY_CREEP_UP": [0.5, 1.0, 2.0, 3.0],          # % capacity gain per cycle
    "LOW_CE": [0.02, 0.04, 0.06, 0.08],                 # drop in first-cycle charge efficiency
    "NOISY_OR_DEAD_CHANNEL": [0.005, 0.010, 0.020, -1], # voltage noise (V); -1 = dead channel
}
LAYOUTS = ("long_semicolon", "wide", "excel_groups", "mat_struct")


def channel_ids(n: int) -> tuple[list[str], list[tuple[int, int]]]:
    cols = 16
    ids, pos = [], []
    for i in range(n):
        r, c = divmod(i, cols)
        ids.append(f"{chr(65 + r)}{c + 1:02d}")
        pos.append((r, c))
    return ids, pos


def make_cells(n: int, seed: int, clean: bool, fault_rate: float) -> tuple[list[Cell], pd.DataFrame]:
    rng = np.random.default_rng(seed)
    ids, pos = channel_ids(n)
    cells, labels = [], []
    faulty = set() if clean else set(rng.choice(n, size=max(1, round(n * fault_rate)), replace=False).tolist())
    fault_names = list(FAULTS)
    for i in range(n):
        r0 = rng.normal(0.025, 0.001)
        cell = Cell(capacity_ah=rng.normal(NOMINAL_AH, 0.015), r0_ohm=r0, r1_ohm=0.6 * r0,
                    first_cycle_ce=rng.normal(0.88, 0.004), creep_pct_per_cycle=rng.normal(0.10, 0.05),
                    ocv_bump_v=rng.normal(0, 0.001), noise_v=0.0005, temp_c=rng.normal(25, 0.3),
                    rng=np.random.default_rng(seed * 1000 + i))
        fault, level, mag = "", -1, 0.0
        if i in faulty:
            fault = fault_names[int(rng.integers(len(fault_names)))]
            level = int(rng.integers(4))
            mag = FAULTS[fault][level]
            if fault == "LOW_CAPACITY":
                cell.capacity_ah *= 1 - mag
            elif fault == "HIGH_IR":
                cell.r0_ohm *= 1 + mag
                cell.r1_ohm *= 1 + mag
            elif fault == "CURVE_SHAPE":
                cell.ocv_bump_v += mag
            elif fault == "CAPACITY_CREEP_UP":
                cell.creep_pct_per_cycle = mag
            elif fault == "LOW_CE":
                cell.first_cycle_ce -= mag
            elif fault == "NOISY_OR_DEAD_CHANNEL":
                if mag < 0:
                    cell.dead = True
                else:
                    cell.noise_v = mag
        cells.append(cell)
        labels.append({"channel_id": ids[i], "row": pos[i][0], "col": pos[i][1], "fault": fault,
                       "severity_level": level, "magnitude": mag})
    return cells, pd.DataFrame(labels)


def build_batch(n: int, seed: int, clean: bool = False, fault_rate: float = 0.12) -> tuple[pd.DataFrame, pd.DataFrame]:
    cells, labels = make_cells(n, seed, clean, fault_rate)
    frames = []
    for cid, cell in zip(labels.channel_id, cells, strict=True):
        cols = simulate_cell(cell, PROTOCOL)
        df = pd.DataFrame(cols)
        df.insert(0, "channel_id", cid)
        frames.append(df)
    canon = pd.concat(frames, ignore_index=True)
    canon["cycle"] = canon["cycle"].astype("int32")
    canon["step"] = canon["step"].astype("int32")
    return canon, labels


# ------------------------------------------------------------------ exporters (invented layouts)

def _hhmmss(seconds: pd.Series) -> pd.Series:
    s = seconds.round().astype("int64")
    return (s // 3600).astype(str).str.zfill(2) + ":" + ((s % 3600) // 60).astype(str).str.zfill(2) + ":" + (s % 60).astype(str).str.zfill(2)


def export_long_semicolon(canon: pd.DataFrame, path: Path, batch: str) -> None:
    """Semicolon CSV, decimal commas, mV/mA, hh:mm:ss test time, 3-line preamble, no capacity column."""
    df = pd.DataFrame({
        "Chan": canon.channel_id, "Cyc": canon.cycle, "Stp": canon.step, "Test Time": _hhmmss(canon.time_s),
        "Volts (mV)": (canon.voltage_v * 1000).round(1), "Amps (mA)": (canon.current_a * 1000).round(1),
        "Temp (C)": canon.temperature_c.round(2)})
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(f"Formation tester export;Batch {batch}\nProgram;FORM3+GRADE1\nStart;2026-10-01 08:00:00\n")
        df.to_csv(f, sep=";", decimal=",", index=False)


def export_wide(canon: pd.DataFrame, path: Path) -> None:
    """One row per tester clock tick (60 s), two columns per channel, no cycle or step columns."""
    grid = np.arange(0, canon.time_s.max() + 60, 60.0)
    out = {"elapsed_min": grid / 60}
    for cid, g in canon.groupby("channel_id", sort=False):
        idx = np.searchsorted(g.time_s.to_numpy(), grid, side="right") - 1
        valid = idx >= 0
        idx = np.clip(idx, 0, len(g) - 1)
        v = np.where(valid, g.voltage_v.to_numpy()[idx], np.nan)
        i = np.where(valid & (grid <= g.time_s.iloc[-1]), g.current_a.to_numpy()[idx], 0.0)
        out[f"{cid}_V"] = np.round(v, 4)
        out[f"{cid}_I"] = np.round(i, 4)
    pd.DataFrame(out).to_csv(path, index=False)


def export_excel_groups(canon: pd.DataFrame, path: Path) -> None:
    """One sheet per tray row; step time resets each step; step-wise capacity in Ah."""
    df = canon.copy()
    first = df.groupby(["channel_id", "step"]).time_s.transform("min")
    df["StepTime(s)"] = (df.time_s - first + 1.0).round(1)
    dt = df.groupby("channel_id").time_s.diff().fillna(0)
    df["Capacity(Ah)"] = (df.current_a.abs() * dt / 3600).groupby([df.channel_id, df.step]).cumsum().round(5)
    df = df.rename(columns={"channel_id": "Channel", "cycle": "Cycle", "step": "Step", "voltage_v": "Voltage(V)",
                            "current_a": "Current(A)", "temperature_c": "Temperature"})
    cols = ["Channel", "Cycle", "Step", "StepTime(s)", "Voltage(V)", "Current(A)", "Capacity(Ah)", "Temperature"]
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        pd.DataFrame({"Info": ["Formation + grading batch", "Sheets = tray rows", "Units: V, A, Ah, degC"]}).to_excel(
            xw, sheet_name="README", index=False)
        for row, g in df.groupby(df.Channel.str[0]):
            g[cols].round(4).to_excel(xw, sheet_name=f"Row_{row}", index=False)


def export_mat_struct(canon: pd.DataFrame, path: Path) -> None:
    """MATLAB struct per channel and cycle; time in hours; current sign flipped (discharge positive)."""
    from scipy.io import savemat

    data = {}
    for cid, g in canon.groupby("channel_id", sort=False):
        cyc = []
        for c, gc in g.groupby("cycle"):
            cyc.append({"cycle_index": int(c), "t_h": (gc.time_s.to_numpy() / 3600).round(6),
                        "U": gc.voltage_v.to_numpy().round(4), "I": (-gc.current_a.to_numpy()).round(4),
                        "T": gc.temperature_c.to_numpy().round(2), "step_index": gc.step.to_numpy().astype(float)})
        data[f"ch_{cid}"] = {"cycles": np.array(cyc, dtype=object)}
    savemat(path, {"tester": data, "info": "sign: discharge current positive; t_h in hours"}, do_compression=True)


EXPORTERS = {
    "long_semicolon": ("export_long.csv", lambda c, p, b: export_long_semicolon(c, p, b)),
    "wide": ("export_wide.csv", lambda c, p, b: export_wide(c, p)),
    "excel_groups": ("export_groups.xlsx", lambda c, p, b: export_excel_groups(c, p)),
    "mat_struct": ("export_struct.mat", lambda c, p, b: export_mat_struct(c, p)),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channels", type=int, default=128)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--clean", action="store_true", help="no planted faults (false-alarm batches)")
    ap.add_argument("--fault-rate", type=float, default=0.12)
    ap.add_argument("--layouts", default="all", help="comma list of " + ",".join(LAYOUTS) + ", or all / none")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    canon, labels = build_batch(a.channels, a.seed, a.clean, a.fault_rate)
    canon.to_parquet(out / "canonical.parquet", index=False)
    labels.to_csv(out / "labels.csv", index=False)
    layouts = LAYOUTS if a.layouts == "all" else () if a.layouts == "none" else tuple(a.layouts.split(","))
    for name in layouts:
        fname, fn = EXPORTERS[name]
        fn(canon, out / fname, out.name)
    meta = {"data_label": "SYNTHETIC", "seed": a.seed, "channels": a.channels, "clean": a.clean,
            "protocol_c_rates": PROTOCOL, "nominal_capacity_ah": NOMINAL_AH, "rows": len(canon),
            "faults": labels.fault.value_counts().drop("", errors="ignore").to_dict(), "layouts": list(layouts),
            "generated_at": (datetime(2026, 10, 1) + timedelta(days=0)).isoformat()}
    (out / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
