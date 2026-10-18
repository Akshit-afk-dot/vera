"""Build contracts/fixtures/* for UI development before the agent works.

FIXTURE ONLY: the numbers are generated from seeded random features (8x8 tray, 4 cycles, 7 planted
faults), then flagged and graded by the real analysis/ code. Token counts and the prices used for
cost are placeholders, not catalog prices. Nothing here is a result; never show it as one.
Run: uv run python scripts/make_fixtures.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pydantic import TypeAdapter  # noqa: E402

from analysis.grading import grade_channel, reference_capacity  # noqa: E402
from analysis.rules import detect  # noqa: E402
from contracts.models import (  # noqa: E402
    BatchResults,
    ColumnMap,
    Event,
    GradeThresholds,
    LayoutMapping,
)

FIX = ROOT / "contracts" / "fixtures"
RUN_ID = "fixture-64ch"
PLANNER, WORKER = "nvidia/nemotron-3-super-120b-a12b", "nvidia/Nemotron-3_5-Lightning"
PLACEHOLDER_PRICE_PER_MTOK = {PLANNER: (0.30, 1.20), WORKER: (0.05, 0.20)}  # FIXTURE PLACEHOLDER
N_CYCLES = 4  # 3 formation + 1 grading

CODE_V1 = '''import json, pandas as pd
from analysis.features import channel_features
from analysis.rules import detect

df = pd.read_parquet("/in/shard.parquet")
feats = channel_features(df, capacity_col="capacity_ah")
flags = detect(list(feats.index), feats.to_dict("list"))
json.dump({"features": feats.reset_index().to_dict("records"), "flags": flags}, open("/out/shard.json", "w"))
'''
CODE_V2 = CODE_V1.replace('capacity_col="capacity_ah"', 'capacity_col=None  # shard has no capacity column: coulomb-count')


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def build_channels(rng: np.random.Generator) -> dict[str, dict]:
    chans = {}
    for r in range(8):
        for c in range(8):
            ch = f"{'ABCDEFGH'[r]}-{c + 1:02d}"
            chans[ch] = {"pos": (r, c), "cap": rng.normal(2.300, 0.010), "ir": rng.normal(38.0, 1.0),
                         "ce1": rng.normal(0.885, 0.004), "peak": rng.normal(3.420, 0.004),
                         "noise": max(0.3, rng.normal(0.8, 0.08)), "slope": rng.normal(0.15, 0.05)}
    chans["A-03"]["cap"] *= 0.94
    chans["C-05"]["ir"] *= 1.6
    chans["D-02"]["slope"] = 1.6
    chans["E-07"].update(cap=0.02, noise=15.0)
    chans["F-01"]["peak"] += 0.045
    chans["G-06"]["ce1"] = 0.84
    chans["H-04"]["cap"] *= 0.975
    return chans


def explanation(flag: dict) -> str:
    e = flag["evidence"][0]
    why = f"robust z {e['robust_z']}" if e["robust_z"] is not None else e["threshold"]
    return (f"{flag['type'].replace('_', ' ').lower()}: {e['metric']} = {e['value']} {e['unit']} versus batch "
            f"median {e['batch_median']} {e['unit']} ({why}).")


def main() -> None:
    rng = np.random.default_rng(20261018)
    chans = build_channels(rng)
    ids = list(chans)
    feats = {
        "capacity_ah": [chans[c]["cap"] for c in ids],
        "ir_mohm": [chans[c]["ir"] for c in ids],
        "first_cycle_ce": [chans[c]["ce1"] for c in ids],
        "dqdv_peak_v": [chans[c]["peak"] for c in ids],
        "capacity_slope_pct_per_cycle": [chans[c]["slope"] for c in ids],
        "noise_mv": [chans[c]["noise"] for c in ids],
    }
    flags = detect(ids, feats)
    th = GradeThresholds()
    ref = reference_capacity(feats["capacity_ah"], th.basis, th.nominal_capacity_ah)
    live_ir = [chans[c]["ir"] for c in ids if not any(f["type"] == "NOISY_OR_DEAD_CHANNEL" for f in flags[c])]
    med_ir = float(np.median(live_ir))
    code_hash = sha(CODE_V2)

    channels = []
    for ch in ids:
        d = chans[ch]
        cycles = []
        for k in range(1, N_CYCLES + 1):
            dis = d["cap"] * (1 + d["slope"] / 100 * (k - N_CYCLES))
            ce = d["ce1"] if k == 1 else rng.normal(0.997, 0.001)
            cycles.append({"cycle": k, "discharge_capacity_ah": round(dis, 4), "charge_capacity_ah": round(dis / ce, 4),
                           "ce": round(ce, 4), "ir_mohm": round(d["ir"], 2) if k == N_CYCLES else None,
                           "mid_voltage_v": round(3.60 + rng.normal(0, 0.002), 4),
                           "dqdv_peak_v": round(d["peak"], 4), "noise_mv": round(d["noise"], 3)})
        for f in flags[ch]:
            f["explanation"] = explanation(f)
        grade = grade_channel(d["cap"], d["ir"], flags[ch], reference_capacity_ah=ref,
                              median_ir_mohm=med_ir, capacity_min_pct=th.capacity_min_pct,
                              ir_max_pct=th.ir_max_pct, reject_on_flags=th.reject_on_flags,
                              max_grade_by_severity=th.max_grade_by_severity)
        channels.append({
            "channel_id": ch, "position": d["pos"], "grade": grade, "capacity_ah": round(d["cap"], 4),
            "ir_mohm": round(d["ir"], 2), "cycles": cycles, "flags": flags[ch],
            "explanation": " ".join(f["explanation"] for f in flags[ch]) or None,
            "provenance": {"run_id": RUN_ID, "code_ids": ["c1", "c2"], "code_sha256": code_hash,
                           "artifacts": [f"sandbox/shard-{ids.index(ch) // 16}/shard.json"]}})

    grade_counts = {g: sum(c["grade"] == g for c in channels) for g in ("A", "B", "C", "REJECT")}
    flag_counts: dict[str, int] = {}
    for c in channels:
        for f in c["flags"]:
            flag_counts[f["type"]] = flag_counts.get(f["type"], 0) + 1
    summary = {"n_channels": len(channels), "n_flagged": sum(bool(c["flags"]) for c in channels),
               "grade_counts": grade_counts, "flag_counts": flag_counts,
               "reference_capacity_ah": round(ref, 4), "median_ir_mohm": round(med_ir, 2)}
    mapping = LayoutMapping(
        format="csv", delimiter=";", decimal=",", header_row=2, time_format="hh:mm:ss",
        columns=[ColumnMap(source="Chan", role="channel_id", unit=""),
                 ColumnMap(source="Cyc", role="cycle", unit=""), ColumnMap(source="Stp", role="step", unit=""),
                 ColumnMap(source="Test Time", role="time_s", unit="hh:mm:ss"),
                 ColumnMap(source="Volts (mV)", role="voltage_v", unit="mV", scale=0.001),
                 ColumnMap(source="Amps (mA)", role="current_a", unit="mA", scale=0.001),
                 ColumnMap(source="Temp", role="temperature_c", unit="degC")],
        confidence=0.86, notes="Semicolon CSV with decimal commas and a 2-line preamble; no capacity column.")
    results = BatchResults(run_id=RUN_ID, data_label="SYNTHETIC", source_name="fixture-64ch (UI development only)",
                           mapping=mapping, thresholds=th, summary=summary, channels=channels)

    # ---------------------------------------------------------------- event timeline
    t = datetime(2026, 10, 18, 18, 0, 0, tzinfo=UTC)
    events: list[dict] = []
    tot = {"in": 0, "out": 0, "cost": 0.0}

    def ev(dt_s: float, type_: str, **body) -> None:
        nonlocal t
        t += timedelta(seconds=dt_s)
        events.append({"v": 0, "run_id": RUN_ID, "seq": len(events), "ts": t.isoformat(), "type": type_, **body})

    def llm(dt_s: float, role: str, purpose: str, tin: int, tout: int) -> None:
        model = PLANNER if role == "planner" else WORKER
        pin, pout = PLACEHOLDER_PRICE_PER_MTOK[model]
        cost = round((tin * pin + tout * pout) / 1e6, 6)
        tot["in"] += tin
        tot["out"] += tout
        tot["cost"] += cost
        ev(dt_s, "llm.call", role=role, model=model, purpose=purpose, tokens_in=tin, tokens_out=tout,
           latency_ms=int(dt_s * 1000), cost_usd=cost)

    ev(0, "run.started", source={"kind": "sample", "name": "fixture-64ch.csv", "size_bytes": 18_874_368,
                                 "sha256": sha("fixture-64ch"), "data_label": "SYNTHETIC"},
       mode="replay", runner="contree", models={"planner": PLANNER, "worker": WORKER})
    llm(6.2, "planner", "infer file layout from a 40-line sample", 2900, 610)
    ev(0.1, "schema.proposed", tier="declarative", attempt=1, mapping=mapping.model_dump())
    ev(1.4, "schema.validated", ok=True, n_channels=64, n_cycles=4, n_rows=1_843_200, checks=[
        {"name": "voltage range 2.0-4.5 V", "ok": True, "detail": "min 2.71 V, max 4.20 V"},
        {"name": "time monotonic per channel", "ok": True, "detail": "64/64 channels"},
        {"name": "current sign consistent", "ok": True, "detail": "charge steps positive"},
        {"name": "at least one channel", "ok": True, "detail": "64 channels"}])
    llm(9.8, "planner", "plan analysis and write code", 5200, 1450)
    ev(0.1, "code.generated", code_id="c1", purpose="per-channel features and flags", attempt=1,
       sha256=sha(CODE_V1), code=CODE_V1)
    for s in range(4):
        ev(0.2, "sandbox.started", runner="contree", code_id="c1", shard=s, n_shards=4,
           channels=ids[s * 16:(s + 1) * 16], operation_id=f"op-fixture-{s}")
    for s in (0, 1, 3):
        ev(7.5, "sandbox.finished", code_id="c1", shard=s, ok=True, exit_code=0, duration_s=11.2,
           stdout_tail="wrote /out/shard.json", artifacts=[f"sandbox/shard-{s}/shard.json"], operation_id=f"op-fixture-{s}")
        ev(0.0, "analysis.progress", done=[0, 1, 3].index(s) + 1, total=4, unit="shards")
    ev(0.4, "sandbox.finished", code_id="c1", shard=2, ok=False, exit_code=1, duration_s=4.1,
       stderr_tail="Traceback (most recent call last):\n  ...\nKeyError: 'capacity_ah'", operation_id="op-fixture-2")
    ev(0.1, "repair.attempt", attempt=1, max_attempts=3, failed_code_id="c1",
       error_summary="KeyError: 'capacity_ah' (this export has no capacity column)")
    llm(7.1, "planner", "repair failed code from traceback", 3100, 520)
    ev(0.1, "code.generated", code_id="c2", purpose="features with coulomb counting", attempt=2,
       sha256=code_hash, code=CODE_V2)
    ev(0.2, "sandbox.started", runner="contree", code_id="c2", shard=2, n_shards=4, channels=ids[32:48],
       operation_id="op-fixture-2b")
    ev(11.9, "sandbox.finished", code_id="c2", shard=2, ok=True, exit_code=0, duration_s=11.6,
       stdout_tail="wrote /out/shard.json", artifacts=["sandbox/shard-2/shard.json"], operation_id="op-fixture-2b")
    ev(0.0, "analysis.progress", done=4, total=4, unit="shards")
    llm(2.3, "worker", "propose grade thresholds with reasons", 1800, 260)
    ev(0.1, "thresholds.proposed", thresholds={**th.model_dump(), "source": "agent",
       "rationale": "Batch spread is tight (MAD-sigma under 0.5% of median), so default bins apply."})
    ev(0.3, "results.ready", summary=summary)
    for ftype in sorted(flag_counts):
        llm(1.6, "worker", f"explain {ftype} flags", 900, 180)
    llm(4.2, "worker", "write QC report narrative", 2600, 700)
    ev(0.2, "verify.claim_failed", sentence="Median capacity was 2.31 Ah.", claim="2.31",
       reason=f"computed reference capacity is {summary['reference_capacity_ah']} Ah", action="regenerated")
    llm(1.1, "worker", "regenerate failed sentence", 700, 60)
    ev(0.2, "verify.summary", claims_checked=23, claims_failed=1, sentences_regenerated=1, sentences_dropped=0)
    ev(0.4, "report.ready", formats=["md"])
    duration = (t - datetime(2026, 10, 18, 18, 0, 0, tzinfo=UTC)).total_seconds()
    ev(0.0, "run.finished", duration_s=duration, tokens_in=tot["in"], tokens_out=tot["out"],
       cost_usd=round(tot["cost"], 6))

    adapter = TypeAdapter(Event)
    for e in events:
        adapter.validate_python(e)

    report = [f"# QC report: {results.source_name}", "",
              "> SYNTHETIC fixture for UI development. Not a result.", "",
              f"**{summary['n_channels']} channels**, reference capacity {summary['reference_capacity_ah']} Ah "
              f"(batch median), median IR {summary['median_ir_mohm']} mOhm.", "",
              "| Grade | Channels |", "|---|---|", *[f"| {g} | {n} |" for g, n in grade_counts.items()], "",
              "## Flagged channels", ""]
    for c in channels:
        if c["flags"]:
            report.append(f"- **{c['channel_id']}** (grade {c['grade']}): {c['explanation']}")

    FIX.mkdir(parents=True, exist_ok=True)
    lf = {"encoding": "utf-8", "newline": "\n"}
    (FIX / "sample_results.json").write_text(results.model_dump_json(indent=1) + "\n", **lf)
    (FIX / "sample_run.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n", **lf)
    (FIX / "sample_report.md").write_text("\n".join(report) + "\n", **lf)
    print(f"{len(events)} events, {summary['n_flagged']} flagged, grades {grade_counts}, flags {flag_counts}")


if __name__ == "__main__":
    main()
