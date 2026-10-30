"""R2: planted-fault detection on SYNTHETIC batches (simulated cells + planted faults), no LLM involved.

Detection is deterministic code (analysis/), so R2 measures the rules themselves against two baselines on the
same features: classic mean/std z-scores and an Isolation Forest. Seeds are fixed before looking at results.
Writes results/r2_detection.json and results/r2_detection.md.

uv run python -m eval.detection
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
from sklearn.ensemble import IsolationForest

from analysis.features import channel_features
from analysis.rules import RULES, Z_FLAG, detect
from synthetic.generate import FAULTS, build_batch

ROOT = Path(__file__).resolve().parent.parent
FAULTY_SEEDS = [11, 12, 13, 14, 15, 16]
CLEAN_SEEDS = [101, 102, 103, 104]
CHANNELS, FAULT_RATE = 128, 0.20
FEATURES = list(RULES)
SWEEP = [2.5, 3.0, 3.5, 4.0, 5.0]


def zscore_flags(feats: pd.DataFrame, z_flag: float = 3.0) -> dict[str, set[str]]:
    out = {ch: set() for ch in feats.index}
    for name, (fault, direction, _, _) in RULES.items():
        x = feats[name].astype(float)
        z = (x - x.mean()) / (x.std() or 1)
        hit = z < -z_flag if direction < 0 else z > z_flag
        for ch in x.index[hit.fillna(False)]:
            out[ch].add(fault)
    return out


def iforest_flags(feats: pd.DataFrame, seed: int) -> set[str]:
    x = feats[FEATURES].astype(float)
    x = (x - x.median()) / (x.std() + 1e-12)
    x = x.fillna(0.0)
    model = IsolationForest(n_estimators=300, contamination="auto", random_state=seed).fit(x)
    return set(x.index[model.predict(x) == -1])


def iforest_method(b: dict) -> dict[str, set[str]]:
    if "iforest" not in b:  # fit once per batch
        b["iforest"] = iforest_flags(b["feats"], b["seed"])
    return {ch: ({"ANY"} if ch in b["iforest"] else set()) for ch in b["feats"].index}


def run_batches() -> list[dict]:
    batches = []
    for seed, clean in [(s, False) for s in FAULTY_SEEDS] + [(s, True) for s in CLEAN_SEEDS]:
        t0 = time.perf_counter()
        canon, labels = build_batch(CHANNELS, seed, clean=clean, fault_rate=FAULT_RATE)
        feats, _, _ = channel_features(canon)
        batches.append({"seed": seed, "clean": clean, "labels": labels.fillna("").set_index("channel_id"),
                        "feats": feats})
        print(f"seed {seed} ({'clean' if clean else 'faulty'}): {time.perf_counter() - t0:.1f} s", flush=True)
    return batches


def typed_counts(batches: list[dict], method) -> dict[str, dict[str, int]]:
    """method(batch) -> {channel: set(fault types)}; counts per fault type."""
    c = {f: {"tp": 0, "fp": 0, "fn": 0} for f in FAULTS}
    for b in batches:
        pred = method(b)
        for ch, row in b["labels"].iterrows():
            truth = row["fault"]
            for f in FAULTS:
                p, t = f in pred[ch], truth == f
                c[f]["tp"] += p and t
                c[f]["fp"] += p and not t
                c[f]["fn"] += t and not p
    return c


def prf(tp: int, fp: int, fn: int) -> dict[str, float | None]:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f1 = 2 * p * r / (p + r) if p and r else 0.0 if p is not None and r is not None else None
    return {"precision": p, "recall": r, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


def detection_level(batches: list[dict], flagged) -> dict:
    """flagged(batch) -> set of channels flagged with anything."""
    tp = fp = fn = clean_n = clean_flagged = 0
    by_level = {lvl: [0, 0] for lvl in range(4)}
    for b in batches:
        f = flagged(b)
        for ch, row in b["labels"].iterrows():
            faulty = row["fault"] != ""
            if faulty:
                tp += ch in f
                fn += ch not in f
                by_level[int(row["severity_level"])][0] += ch in f
                by_level[int(row["severity_level"])][1] += 1
            else:
                fp += ch in f
                if b["clean"]:
                    clean_n += 1
                    clean_flagged += ch in f
    return {**prf(tp, fp, fn), "false_alarm_rate_clean_batches": clean_flagged / clean_n if clean_n else None,
            "recall_by_severity_level": {lvl: (h / n if n else None) for lvl, (h, n) in by_level.items()}}


def main() -> None:
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    batches = run_batches()

    def rules_at(z):
        def m(b):
            fl = detect(list(b["feats"].index), {k: b["feats"][k].tolist() for k in FEATURES}, z_flag=z)
            return {ch: {f["type"] for f in fs} for ch, fs in fl.items()}
        return m

    methods = {
        f"Vera rules (robust z, |z|>{Z_FLAG})": (rules_at(Z_FLAG), True),
        "Baseline: mean/std z-score (|z|>3)": (lambda b: zscore_flags(b["feats"]), True),
        "Baseline: Isolation Forest (untyped)": (iforest_method, False),
    }
    report = {"data_label": "SYNTHETIC", "channels_per_batch": CHANNELS, "fault_rate": FAULT_RATE,
              "faulty_seeds": FAULTY_SEEDS, "clean_seeds": CLEAN_SEEDS,
              "n_faulty_channels": int(sum((b["labels"].fault != "").sum() for b in batches)),
              "n_clean_batch_channels": CHANNELS * len(CLEAN_SEEDS), "methods": {}}
    for name, (m, typed) in methods.items():
        entry = {"detection": detection_level(batches, lambda b, m=m: {ch for ch, s in m(b).items() if s})}
        if typed:
            counts = typed_counts(batches, m)
            entry["by_fault_type"] = {f: prf(**c) for f, c in counts.items()}
            tot = {k: sum(c[k] for c in counts.values()) for k in ("tp", "fp", "fn")}
            entry["typed_micro"] = prf(**tot)
        report["methods"][name] = entry
    report["sweep"] = {str(z): detection_level(batches, lambda b, z=z: {ch for ch, s in rules_at(z)(b).items() if s})
                       for z in SWEEP}
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    (out / "r2_detection.json").write_text(json.dumps(report, indent=1, default=float), encoding="utf-8", newline="\n")
    (out / "r2_detection.md").write_text(to_markdown(report), encoding="utf-8", newline="\n")
    web = ROOT / "web" / "data"
    web.mkdir(parents=True, exist_ok=True)
    (web / "r2.json").write_text(json.dumps(report, default=float), encoding="utf-8", newline="\n")
    print(to_markdown(report))


def _f(x) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def to_markdown(r: dict) -> str:
    lines = [f"**R2: planted-fault detection [SYNTHETIC]** · {len(r['faulty_seeds'])} faulty batches "
             f"({r['n_faulty_channels']} planted faults) + {len(r['clean_seeds'])} clean batches "
             f"({r['n_clean_batch_channels']} channels) · {r['channels_per_batch']} channels each", "",
             "| Method | Precision | Recall | F1 | Typed F1 | False alarms on clean batches |", "|---|---|---|---|---|---|"]
    for name, e in r["methods"].items():
        d = e["detection"]
        typed = _f(e["typed_micro"]["f1"]) if "typed_micro" in e else "untyped"
        lines.append(f"| {name.replace('|', chr(92) + '|')} | {_f(d['precision'])} | {_f(d['recall'])} | {_f(d['f1'])} | {typed} | "
                     f"{100 * d['false_alarm_rate_clean_batches']:.2f}% |")
    vera = next(iter(r["methods"].values()))
    lines += ["", "Recall by fault type and severity (Vera rules):", "",
              "| Fault | Precision | Recall | F1 |", "|---|---|---|---|"]
    for f, m in vera["by_fault_type"].items():
        lines.append(f"| {f} | {_f(m['precision'])} | {_f(m['recall'])} | {_f(m['f1'])} |")
    lv = vera["detection"]["recall_by_severity_level"]
    lines += ["", "| Severity level (mildest → strongest) | 0 | 1 | 2 | 3 |", "|---|---|---|---|---|",
              "| Recall | " + " | ".join(_f(lv[k]) for k in sorted(lv)) + " |", "",
              "Threshold sweep (Vera rules, any-fault detection):", "",
              "| \\|z\\| threshold | Precision | Recall | False alarms on clean batches |", "|---|---|---|---|"]
    for z, d in r["sweep"].items():
        lines.append(f"| {z} | {_f(d['precision'])} | {_f(d['recall'])} | {100 * d['false_alarm_rate_clean_batches']:.2f}% |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
