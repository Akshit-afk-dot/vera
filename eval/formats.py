"""R1: does Vera read unfamiliar layouts correctly? Scores finished runs against ground truth.

SYNTHETIC layouts: the ingested canonical table is compared with the generator's ground-truth table through the
features Vera grades on (capacity, first-cycle CE, resistance), channel by channel.
REAL files: compared with hand-written answer keys (eval/answer_keys/*.yaml), never with the files' READMEs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from analysis.features import channel_features

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Case:
    name: str
    run_id: str
    label: str
    truth: Path            # ground-truth canonical.parquet (synthetic) or answer key yaml (real)
    note: str = ""
    extra: dict = field(default_factory=dict)


def run_facts(run_id: str) -> dict:
    d = ROOT / "runs" / run_id
    if not (d / "events.jsonl").exists():
        return {"ingested": False, "error": "run not found"}
    ev = [json.loads(x) for x in (d / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    planner_codes = [e for e in ev if e["type"] == "code.generated" and "memory" not in e["purpose"]]
    validated = [e for e in ev if e["type"] == "schema.validated"]
    return {"ingested": any(v["ok"] for v in validated), "attempts": len(planner_codes),
            "repairs": sum(e["type"] == "repair.attempt" for e in ev), "memory_hit": any(e["type"] == "memory.hit" for e in ev),
            "failed": next((e["error"] for e in ev if e["type"] == "run.failed"), None),
            "canonical": d / "work" / "canonical.parquet"}


def _match_ids(truth_ids, got_ids) -> dict[str, str]:
    got = list(got_ids)
    out = {}
    for t in truth_ids:
        m = next((g for g in got if g == t or g.endswith(str(t)) or str(t).endswith(g)), None)
        if m is not None:
            out[t] = m
    return out


def score_synthetic(case: Case, facts: dict) -> dict:
    truth_f, _, _ = channel_features(pd.read_parquet(case.truth))
    got_f, _, _ = channel_features(pd.read_parquet(facts["canonical"]))
    ids = _match_ids(list(truth_f.index), list(got_f.index))
    rows = []
    for t, g in ids.items():
        a, b = truth_f.loc[t], got_f.loc[g]
        rows.append({"cap_rel": abs(b.capacity_ah - a.capacity_ah) / a.capacity_ah if a.capacity_ah else np.nan,
                     "ce_abs": abs(b.first_cycle_ce - a.first_cycle_ce) if pd.notna(b.first_cycle_ce) and pd.notna(a.first_cycle_ce) else np.nan,
                     "ir_rel": abs(b.ir_mohm - a.ir_mohm) / a.ir_mohm if pd.notna(b.ir_mohm) and pd.notna(a.ir_mohm) else np.nan,
                     "cycles_ok": b.n_cycles == a.n_cycles})
    r = pd.DataFrame(rows)
    live = r[np.isfinite(r.cap_rel)]
    return {"channels": f"{len(ids)}/{len(truth_f)}",
            "capacity_within_1pct": float((live.cap_rel <= 0.01).mean()) if len(live) else None,
            "ce_within_0.01": float((r.ce_abs.dropna() <= 0.01).mean()) if r.ce_abs.notna().any() else None,
            "ir_within_10pct": float((r.ir_rel.dropna() <= 0.10).mean()) if r.ir_rel.notna().any() else None,
            "cycles_match": float(r.cycles_ok.mean()) if len(r) else None}


def score_real(case: Case, facts: dict) -> dict:
    key = yaml.safe_load(case.truth.read_text(encoding="utf-8"))
    canon = pd.read_parquet(facts["canonical"])
    f, cycles, _ = channel_features(canon)
    want = key["channels"]["ids"] if case.extra.get("channels") is None else case.extra["channels"]
    ids = _match_ids(want, list(f.index))
    out = {"channels": f"{len(ids)}/{len(want)}"}
    ref = key.get("reference_values", {}) if case.extra.get("channels") is None else {}
    if "first_discharge_capacity_ah" in ref and want[0] in ids:
        first = cycles[ids[want[0]]][0]["discharge_capacity_ah"]
        out["first_discharge_capacity_ok"] = abs(first - ref["first_discharge_capacity_ah"]) / ref["first_discharge_capacity_ah"] <= 0.01
    if ref and "count" in key.get("cycles", {}) and want[0] in ids:
        out["cycles_match"] = abs(len(cycles[ids[want[0]]]) - key["cycles"]["count"]) <= 2
    if "c1dc_capacity_mah_first_to_last" in ref and len(ids) == len(want):
        caps = {t: f.loc[g].capacity_ah for t, g in ids.items()}
        lowest = min(caps, key=caps.get)
        out["lowest_final_capacity_is_Cell5"] = lowest == "Cell5"
    return out


def evaluate(cases: list[Case]) -> list[dict]:
    rows = []
    for c in cases:
        facts = run_facts(c.run_id)
        row = {"case": c.name, "label": c.label, "run_id": c.run_id, "note": c.note,
               **{k: v for k, v in facts.items() if k != "canonical"}}
        if facts.get("ingested") and facts["canonical"].exists():
            try:
                row.update(score_synthetic(c, facts) if c.truth.suffix == ".parquet" else score_real(c, facts))
            except Exception as e:  # noqa: BLE001 - a scoring failure is reported, not hidden
                row["score_error"] = f"{type(e).__name__}: {e}"
        rows.append(row)
    return rows


def to_markdown(rows: list[dict]) -> str:
    def pct(x):
        return "n/a" if x is None else (("yes" if x else "no") if isinstance(x, bool) else f"{100 * x:.0f}%")

    lines = ["| File | Data | Read correctly | Model attempts | Channels found | Capacity within 1% | First-cycle CE within 0.01 | IR within 10% | Cycles match |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['case']} | {r['label']} | {'yes' if r.get('ingested') else 'no'}{' (learned format)' if r.get('memory_hit') else ''} | "
                     f"{r.get('attempts', 'n/a')} | {r.get('channels', 'n/a')} | {pct(r.get('capacity_within_1pct', r.get('first_discharge_capacity_ok')))} | "
                     f"{pct(r.get('ce_within_0.01'))} | {pct(r.get('ir_within_10pct'))} | {pct(r.get('cycles_match'))} |")
    return "\n".join(lines) + "\n"
