"""Fixture for the Python <-> TypeScript engine parity test (forge-app/test/parity.test.ts).

Writes forge-app/test/fixtures/batch.csv.gz (canonical table, SYNTHETIC, 16 channels with planted faults) and
expected.json (features, flags and grades computed by the Python engine from that same CSV).
uv run python scripts/make_parity_fixture.py
"""

from __future__ import annotations

import gzip
import io
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from analysis.features import channel_features  # noqa: E402
from analysis.grading import grade_channel, reference_capacity  # noqa: E402
from analysis.rules import detect  # noqa: E402
from contracts.models import GradeThresholds  # noqa: E402
from synthetic.generate import build_batch, export_long_semicolon, export_wide  # noqa: E402

OUT = ROOT / "forge-app" / "test" / "fixtures"
RULE_FEATURES = ["capacity_ah", "ir_mohm", "first_cycle_ce", "curve_dist_pct", "capacity_slope_pct_per_cycle", "noise_mv"]


def clean(x):
    return None if x is None or (isinstance(x, float) and x != x) else x


def main() -> None:
    canon, labels = build_batch(16, seed=21, fault_rate=0.35)
    cols = ["channel_id", "cycle", "step", "time_s", "voltage_v", "current_a"]
    csv_text = canon[cols].to_csv(index=False, float_format="%.6f", lineterminator="\n")
    OUT.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT / "batch.csv.gz", "wt", encoding="utf-8", newline="\n") as f:
        f.write(csv_text)
    df = pd.read_csv(io.StringIO(csv_text), dtype={"channel_id": str})   # exactly what TypeScript will read

    feats, cycles, _ = channel_features(df)
    ids = list(feats.index)
    flags = detect(ids, {k: feats[k].tolist() for k in RULE_FEATURES})
    th = GradeThresholds()
    ref = reference_capacity(feats.capacity_ah.tolist(), th.basis, th.nominal_capacity_ah)
    noisy = {c for c in ids if any(f["type"] == "NOISY_OR_DEAD_CHANNEL" for f in flags[c])}
    med_ir = float(feats.ir_mohm[[c not in noisy for c in ids]].dropna().median())
    grades = {c: grade_channel(clean(feats.loc[c, "capacity_ah"]), clean(feats.loc[c, "ir_mohm"]), flags[c],
                               reference_capacity_ah=ref, median_ir_mohm=med_ir, capacity_min_pct=th.capacity_min_pct,
                               ir_max_pct=th.ir_max_pct, reject_on_flags=th.reject_on_flags,
                               max_grade_by_severity=th.max_grade_by_severity) for c in ids}
    expected = {
        "data_label": "SYNTHETIC",
        "planted": labels.fillna("").set_index("channel_id")["fault"].to_dict(),
        "features": {c: {k: clean(float(v)) if v is not None else None for k, v in feats.loc[c].items()} for c in ids},
        "cycles": cycles,
        "flags": {c: [{"type": f["type"], "severity": f["severity"]} for f in flags[c]] for c in ids},
        "reference_capacity_ah": ref, "median_ir_mohm": med_ir, "grades": grades,
        "thresholds": th.model_dump(),
    }
    (OUT / "expected.json").write_text(json.dumps(expected, indent=1), encoding="utf-8", newline="\n")
    # The same batch in two invented tester layouts, for the Forge reader and pipeline tests
    for name, fn in (("export_long.csv", lambda p: export_long_semicolon(canon, p, "parity")), ("export_wide.csv", lambda p: export_wide(canon, p))):
        tmp = OUT / name
        fn(tmp)
        with tmp.open("rb") as src, gzip.open(OUT / f"{name}.gz", "wb") as dst:
            dst.write(src.read())
        tmp.unlink()
    size = (OUT / "batch.csv.gz").stat().st_size
    print(f"{len(df)} rows, {len(ids)} channels, {size / 1e3:.0f} kB gz; flagged: "
          f"{ {c: [f['type'] for f in fs] for c, fs in flags.items() if fs} }")


if __name__ == "__main__":
    main()
